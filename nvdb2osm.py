#!/usr/bin/env python3
# -*- coding: utf8

# nvdb2osm.py
# Converts road objects and road networks from NVDB to OSM file format
# Usage:
# 1) nvdb2osm -vegobjekt <vegobjektkode> [-kommune <kommune>] > outfile.osm  --> Produces osm file with all road objects of a given type (optionally within a given municipality)
# 2) nvdb2osm -vegnett -kommune <kommune> > outfile.osm  --> Produces osm file with road network for a given municipality
# 3) nvdb2osm -vegref <vegreferanse> > outfile.osm  --> Produces osm file with road network for given road reference code
# 4) nvdb2osm -vegurl "<http string from vegnett.no>"" > outfile.osm  --> Produces osm file defined by given NVDB http api call from vegkart.no.
#       "&srid=wgs84" automatically added. Bounding box only supported for wgs84 coordinates, not UTM from vegkart.no. 

import json
import urllib.request
import sys
import socket
import os
import copy
import math
import calendar
import time
from xml.etree import ElementTree as ET


version = "1.6.0"

longer_ways = True      # True: Concatenate segments with identical tags into longer ways, within sequence
debug = False           # True: Include detailed information tags for debugging
save_input = False		# True: Save raw input from api to file
include_objects = True  # True: Include road objects in network output
object_tags = False     # True: Include detailed road object information tags
date_filter = None      # Limit data to given date, for example "2020-05" to get highways created in May 2020

segment_margin = 10.0   # Tolerance for snap of way property to way start/end (meters)
point_margin = 2.0      # Tolerance for snap of point to way start/end (meters)
node_margin = 1.0       # Tolerance for snap of point to nodes of way (meters)
fix_margin = 0.5   		# Minimum distance between way nodes (meters)
angle_margin = 45.0     # Maximum change of bearing at intersection for merging segments into longer ways (degrees)
max_travel_depth = 10   # Maximum depth of recursive calls when finding route
simplify_factor = 0.2	# Minimum deviation to straight line before simplification of redundant nodes (meters)
years_back = 1			# Maximum number of years between survey of road ("datafangst") and start date (for date option)

import_folder = "~/Jottacloud/osm/nvdb nye/log/"  # Folder containing json with history of road network for each month

#server = "https://nvdbapiles-v3.utv.atlas.vegvesen.no/"  # UTV - Utvikling
#server = "https://nvdbapiles-v3-stm.utv.atlas.vegvesen.no/"  # STM - Systemtest
#server = "https://nvdbapiles-v3.test.atlas.vegvesen.no/"  # ATM - Testproduksjon
server = "https://nvdbapiles-v3.atlas.vegvesen.no/"  # Produksjon

request_headers = {
	"X-Client": "nvdb2osm",
	"X-Kontaktperson": "nkamapper@gmail.com",
	"Accept": "application/vnd.vegvesen.nvdb-v3-rev1+json"
}

road_category = {
	'E': {'name': 'Europaveg',    'tag': 'trunk'},
	'R': {'name': 'Riksveg',      'tag': 'trunk'},
	'F': {'name': 'Fylkesveg',    'tag': 'secondary'},
	'K': {'name': 'Kommunal veg', 'tag': 'residential'},
	'P': {'name': 'Privat veg',   'tag': 'service'},
	'S': {'name': 'Skogsbilveg',  'tag': 'service'}
}

road_status = {
	'V': 'Eksisterende veg',
	'A': 'Veg under bygging',
	'P': 'Planlagt veg',
	'F': 'Fiktiv veg'
}

medium_types = {
	'T': 'På terrenget/på bakkenivå',
	'B': 'I bygning/bygningsmessig anlegg',
	'L': 'I luft',
	'U': 'Under terrenget',
	'S': 'På sjøbunnen',
	'O': 'På vannoverflaten',
	'V': 'Alltid i vann',
	'D': 'Tidvis under vann',
	'I': 'På isbre',
	'W': 'Under sjøbunnen',
	'J': 'Under isbre',
	'X': 'Ukjent'
}



# Extension of dict class which returns an empty string if element does not exist

class Properties(dict):
    def __missing__(self, key):
        return ""



# Write message to console

def message (text):

	sys.stderr.write(text)
	sys.stderr.flush()



# Open URL request. Retry if needed.

def open_url (url):

	tries = 0
	while tries <= 5:
		try:
			return urllib.request.urlopen(url)
		except Exception as err:  #(urllib.error.HTTPError, ConnectionResetError) as err:
			if tries == 5:
				raise
			elif tries == 0:
				message ("\n") 
			message ("Retry %i: %s\n" % (tries + 1, err))
			time.sleep(5 * (2**tries))
			tries += 1



# Load data from api. Retry if needed.

def load_data (url):

	tries = 0
	while tries <= 5:
		try:
			request = urllib.request.Request(url, headers=request_headers)
			file = urllib.request.urlopen(request)
			data = json.load(file)
			file.close()
			return data

		except Exception as err:
			if tries == 5:
				raise
			elif tries == 0:
				message ("\n") 
			message ("Retry %i: %s\n" % (tries + 1, err))
			time.sleep(5 * (2**tries))
			tries += 1



# Compute approximation of distance between two coordinates, (lat,lon), in kilometers
# Works for short distances

def compute_distance (point1, point2):

	lon1, lat1, lon2, lat2 = map(math.radians, [point1[1], point1[0], point2[1], point2[0]])
	x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
	y = lat2 - lat1
	return 6371000.0 * math.sqrt( x*x + y*y )  # Metres



# Return bearing in degrees of line between two points (latitude, longitude)

def compute_bearing (point1, point2):

	lon1, lat1, lon2, lat2 = map(math.radians, [point1[1], point1[0], point2[1], point2[0]])
	dLon = lon2 - lon1
	y = math.sin(dLon) * math.cos(lat2)
	x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
	angle = (math.degrees(math.atan2(y, x)) + 360) % 360
	return angle



# Compute closest distance from point p3 to line segment [s1, s2].
# Works for short distances.

def line_distance(s1, s2, p3):

	x1, y1, x2, y2, x3, y3 = map(math.radians, [s1[1], s1[0], s2[1], s2[0], p3[1], p3[0]])  # Note: (y,x)

	# Simplified reprojection of latitude
	x1 = x1 * math.cos( y1 )
	x2 = x2 * math.cos( y2 )
	x3 = x3 * math.cos( y3 )

	A = x3 - x1
	B = y3 - y1
	dx = x2 - x1
	dy = y2 - y1

	dot = (x3 - x1)*dx + (y3 - y1)*dy
	len_sq = dx*dx + dy*dy

	if len_sq != 0:  # in case of zero length line
		param = dot / len_sq
	else:
		param = -1

	if param < 0:
		x4 = x1
		y4 = y1
	elif param > 1:
		x4 = x2
		y4 = y2
	else:
		x4 = x1 + param * dx
		y4 = y1 + param * dy

	# Also compute distance from p to segment

	x = x4 - x3
	y = y4 - y3
	distance = 6371000 * math.sqrt( x*x + y*y )  # In meters

	'''
	# Project back to longitude/latitude

	x4 = x4 / math.cos(y4)

	lon = math.degrees(x4)
	lat = math.degrees(y4)

	return (lon, lat, distance)
	'''

	return distance



# Fix street name initials/dots and spacing + corrections table.
# Same algorithm as in addr2osm.
# Examples:
#   Dr.Gregertsens vei -> Dr. Gregertsens vei
#   Arne M Holdens vei -> Arne M. Holdens vei
#   O G Hauges veg -> O.G. Hauges veg
#   C. A. Pihls gate -> C.A. Pihls gate

def fix_street_name (name):

	# First test exceptions from Github json file

	name = name.replace("  ", " ").strip()

	if name in name_corrections:
		return name_corrections[ name ]

	# Loop characters in street name and make automatic corrections for dots and spacing

	new_name = ""
	length = len(name)

	i = 0
	word = 0  # Length of last word while looping street name

	while i < length - 3:  # Avoid last 3 characters to enable forward looking tests

		if name[i] == ".":
			if name[i + 1] == " " and name[i + 3] in [".", " "]:  # Example "C. A. Pihls gate"
				new_name = new_name + "." + name[i + 2]
				i += 2
				word = 1
			elif name[i + 1] != " " and name[i + 2] not in [".", " "]:  # Example "Dr.Gregertsens vei"
				new_name = new_name + ". "
				word = 0
			else:
				new_name = new_name + "."
				word = 0

		elif name[i] == " ":
			# Avoid "Elvemo / Bávttevuolbállggis", "Skjomenveien - Elvegård", "Bakken i Lysefjorden", "Kristian 4 gate"
			if word == 1 and name[i-1] not in ["-", "/", "i"] and not name[i-1].isdigit():
				if name[i + 2] in [" ", "."]:  # Example "O G Hauges veg"
					new_name = new_name + "."
				else:
					new_name = new_name + ". "  # Example "K Sundts vei"
			else:
				new_name = new_name + " "
			word = 0

		else:
			new_name = new_name + name[i]
			word += 1

		i += 1

	new_name = new_name + name[i:i + 3]

	# Check correction table for last part of name

	split_name = new_name.split()
	for i in range(1, len(split_name)):
		if split_name[i] in name_ending_corrections:
			split_name[i] = split_name[i].lower()
			new_name = " ".join(split_name)

	if name != new_name:
		return new_name
	else:
		return name



# Generate display road number

def get_ref (category, number):

	if category == "E":
		ref = "E " + str(number)
	elif category in ["R", "F"]:
		ref = str(number)
	else:
		ref = ""

	return ref



# Generate forward/backward direction + NVDB lane code

def get_direction (lane):

	if not lane:
		return ("", "")

	if isinstance(lane, list):
		# Check if all directions are similar
		last_direction = ""
		for one_lane in lane:
			direction, code = get_direction(one_lane)
			if last_direction and direction != last_direction:
				return ("", "")
			last_direction = direction
		return (last_direction, "")

	else:
		# Decompose lane coding
		code = ""
		if len(lane) > 1 and lane[1].isdigit():
			side = lane[0:2]
			if len(lane) > 2:
				code = lane[2].upper()
		else:
			side = lane[0]
			if len(lane) > 1:
				code = lane[1].upper()

		# Odd numbers forward, else backward
		if side[-1] in ["1", "3", "5", "7", "9"]:
			return ("forward", code)
		else:
			return ("backward", code)



# Decode NVDB lane coding to OSM tags

def process_lanes (lane_codes):

	lanes = {}
	turn = {}
	psv = {}
	cycleway = {}
	tags = {}

	for direction in ["forward", "backward"]:
		lanes[direction] = 0
		turn[direction] = ""
		psv[direction] = ""
		cycleway[direction] = False

	# Loop all lanes and build turn:lane tags + count lanes

	for i, lane in enumerate(lane_codes):

		direction, code = get_direction(lane)

		if i == 0:
			segment_reverse = (direction == "backward")

		# Build lane tagging for turn, psv and cycleway
		if code == "V":
			turn[direction] = "|left" + turn[direction]
			psv[direction]  = "|" + psv[direction]
			lanes[direction] += 1
		elif code == "H":
			turn[direction] += "|right"
			psv[direction]  += "|"
			lanes[direction] += 1
		elif code == "K":
			turn[direction] += "|"
			psv[direction]  += "|designated"
			lanes[direction] += 1
		elif code == "S":
			cycleway[direction] = True
		else:
			turn[direction] += "|through"
			psv[direction] +=  "|"
			lanes[direction] += 1

	# Simplify turn and psv tagging if all lanes are equal

	for direction in ["forward", "backward"]:

		turn[direction] = turn[direction][1:]
		if "left" not in turn[direction] and "right" not in turn[direction]:
			turn[direction] = ""

		psv[direction] = psv[direction][1:]
		if "designated" not in psv[direction]:
			psv[direction] = ""
		elif psv[direction].replace("|designated", "") == "designated":  # All turns designated
			psv[direction] = "designated"		

	# Produce turn:lane and access tags. Forward and backward tagging only needed if not oneway

	for direction in ["forward", "backward"]:
		if lanes['forward'] > 0 and lanes['backward'] > 0:
			suffix = ":" + direction
		else:
			suffix = ""

		if "|" in turn[direction]:
			tags['turn:lanes' + suffix] = turn[direction]
		elif turn[direction] and lanes['forward'] + lanes['backward'] > 1:
			tags['turn' + suffix] = turn[direction]

		if "|" in psv[direction]:
			tags['psv:lanes' + suffix] = psv[direction]
			tags['motor_vehicle:lanes' + suffix] = psv[direction].replace("designated","no")

		elif psv[direction]:
			if psv['forward'] == psv['backward']:
				suffix = ""
			tags['psv' + suffix] = psv[direction]
			tags['motor_vehicle' + suffix] = psv[direction].replace("designated","no")

	# Lanes tagging if more than one line in either direction

	if lanes['forward'] > 1 or lanes['backward'] > 1 or psv['forward'] or psv['backward'] or \
			(turn['forward'] or turn['backward']) and lanes['forward'] + lanes['backward'] > 1:  
		tags['lanes'] = str(lanes['forward'] + lanes['backward'])

	if lanes['forward'] > 0 and lanes['backward'] > 0 and lanes['forward'] + lanes['backward'] > 2:
		tags['lanes:forward'] = str(lanes['forward'])
		tags['lanes:backward'] = str(lanes['backward'])

 	# One-way if either direction is missing

	if lanes['forward'] == 0 or lanes['backward'] == 0:
		tags['oneway'] = "yes"

	# Produce cycleway lane tags

	if cycleway['forward'] and cycleway['backward']:
		tags['cycleway'] = "lane"
	elif segment_reverse:
		if cycleway['forward']:
			tags['cycleway:left'] = "lane"
		elif cycleway['backward']:
			tags['cycleway:right'] = "lane"
	else:
		if cycleway['forward']:
			tags['cycleway:right'] = "lane"
		elif cycleway['backward']:
			tags['cycleway:left'] = "lane"

	# Remove empty keys

	for key, value in tags.items():
		if not value:
			del tags[key]

	return tags



# Produce basic highway tagging for segment

def tag_highway (segment, lanes, tags, extras):

	if segment['vegsystemreferanse']:
		ref = segment['vegsystemreferanse']['vegsystem']
	else:
		ref = None

	# Set key according to status (proposed, construction, existing)

	tag_key = "highway"
	if ref:
		if ref['fase'] == "A":
			tags['highway'] = "construction"
			tag_key = "construction"
		elif ref['fase'] ==  "P":
			if segment['typeVeg'] in ["Bilferje", "Passasjerferje"]:
				tags['route'] = "proposed"
			else:
				tags['highway'] = "proposed"
			tag_key = "proposed"
		else:
			if segment['typeVeg'] in ["Bilferje", "Passasjerferje"]:
				tag_key = "route"

	# Special case: Strange data tagged as crossing

	if segment['typeVeg'] in ["Kanalisert veg", "Enkel bilveg"] and ref and \
			"strekning" in segment['vegsystemreferanse'] and segment['vegsystemreferanse']['strekning']['trafikantgruppe'] == "G" or \
			segment['typeVeg'] == "Gang- og sykkelveg" and "topologinivå" in segment and segment['topologinivå'] == "KJOREBANE":
		tags[tag_key] = "footway"
		tags['footway'] = "crossing"
		tags['bicycle'] = "yes"
		segment['typeVeg'] == "Gangfelt"

	# Tagging for normal highways (cars)

	elif segment['typeVeg'] in ["Enkel bilveg", "Kanalisert veg", "Rampe", "Rundkjøring"] and ref:  # Regular highways (excluding "kjørefelt")

		if "sideanlegg" in segment['vegsystemreferanse'] or \
				len(lanes) == 1 and "K" in lanes[0] and ref['vegkategori'] in ["E", "R", "F"] and segment['detaljnivå'] != "Kjørebane" and \
				(segment['typeVeg'] != "Enkel bilveg" or "kryssystem" in segment['vegsystemreferanse']): # Trafikklommer/rasteplasser
			tags[tag_key] = "unclassified"

		else:
			if (ref['vegkategori'] == "F" or ref['vegkategori'] == "K" and municipality_id == "0301") and ref['nummer'] < 1000:  # After reform
				tags[tag_key] = "primary"
				tags['ref'] = get_ref("F", ref['nummer'])
			else:
				tags[tag_key] = road_category[ ref['vegkategori'] ]['tag']
				if ref['vegkategori'] in ["E", "R", "F"]:
					tags['ref'] = get_ref(ref['vegkategori'], ref['nummer'])

			# Add Ring ref in Oslo/Bærum
			if ref['nummer'] == 162 and ref['vegkategori'] == "R":
				tags['ref'] += ";Ring 1"
			elif ref['nummer'] == 161 and ref['vegkategori'] == "K":
				tags['ref'] = "161;Ring 2"
			elif (ref['nummer'] == 150 and ref['vegkategori'] == "R"
					or ref['nummer'] == 6 and "gate" in segment and segment['gate']['navn'] in ["Hjalmar Brantings vei", "Adolf Hedins vei"]):
				tags['ref'] += ";Ring 3"

			if tags[tag_key] in ["trunk", "primary", "secondary"]:  # ref['vegkategori'] in ["E", "R", "F"]:
				if segment['typeVeg'] == "Rampe" or segment['detaljnivå'] == "Kjørefelt" and lanes and "H" in lanes[0]:
					tags[tag_key] += "_link"
#				tags['ref'] = get_ref(ref['vegkategori'], ref['nummer'])
				tags['surface'] = "asphalt"  # May be owerwritten later, based on road object info

		if segment['typeVeg'] == "Rundkjøring":
			tags['junction'] = "roundabout"

		if lanes:
			tags.update (process_lanes (lanes))
		elif segment['detaljnivå'] != "Vegtrase" and segment['typeVeg'] in ["Kanalisert veg", "Rampe", "Rundkjøring"]:
			tags['oneway'] = "yes"

		if segment['detaljnivå'] == "Kjørefelt" and not (lanes and ("K" in lanes[0] and lanes[0] != "SVKL")): # or "H" in lanes[0])):
#			tags.clear()
#			tags['FIXME'] = 'Please replace way with "turn:lanes" on main way'
			if tag_key in tags:
				del tags[tag_key]
			if "turn:lanes" in tags:
				del tags['turn:lanes']
#			if lanes and  "V1" in lanes[0] and "turn:lanes" not in tags:
#				tags['turn:lanes'] = "left"

	# Ferries

	elif segment['typeVeg'] in ["Bilferje", "Passasjerferje"]:  # Ferry
		tags[tag_key] = "ferry"
		if ref:
			tags['ref'] = get_ref(ref['vegkategori'], ref['nummer'])
			if ref['vegkategori'] == "F" and ref['nummer'] < 1000:
				tags['ferry'] = "primary"
			else:
				tags['ferry'] = road_category[ ref['vegkategori'] ]['tag'].replace("residential", "unclassified").replace("service", "unclassified")
		else:
			tags['ferry'] = "unclassified"

	# All other highway types

	elif segment['typeVeg'] == "Gågate":  # Pedestrian street
		tags[tag_key] = "pedestrian"
		tags['bicycle'] = "yes"
		tags['surface'] = "asphalt"

	elif segment['typeVeg'] == "Gatetun":  # Living street
		tags[tag_key] = "living_street"

	elif segment['typeVeg'] == "Gang- og sykkelveg":  # Combined cycleway/footway		
		if ref and ref['vegkategori'] != "P":
			tags[tag_key] = "cycleway"
			tags['foot'] = "designated"
			tags['segregated'] = "no"
			tags['surface'] = "asphalt"
		else:
			tags[tag_key] = "footway"
			tags['bicycle'] = "yes"
			tags['segregated'] = "no"

	elif segment['typeVeg'] == "Sykkelveg":  # Express cycleway
		tags[tag_key] = "cycleway"
		tags["foot"] = "designated"
		tags['segregated'] = "yes"
		tags['surface'] = "asphalt"
		if len(lanes) == 2 and lanes[0] == "1S" and lanes[1] == "2S":
			tags['lanes'] = "2"

	elif segment['typeVeg'] == "Gangveg":  # Footway
		tags[tag_key] = "footway"
		tags['bicycle'] = "yes"

	elif segment['typeVeg'] == "Fortau":  # Sidewalk
		tags[tag_key] = "footway"
#		tags['bicycle'] = "yes"
		tags['footway'] = "sidewalk"

	elif segment['typeVeg'] == "Gangfelt":  # Crossing
		tags[tag_key] = "footway"
#		tags['bicycle'] = "yes"
		tags['footway'] = "crossing"

	elif segment['typeVeg'] == "Trapp":  # Stairs
		tags[tag_key] = "steps"

	elif segment['typeVeg'] == "Traktorveg":  # Track
		tags[tag_key] = "track"

	elif segment['typeVeg'] == "Sti":  # Path
		tags[tag_key] = "path"

	elif segment['typeVeg'] == "Annet":  # Other
		tags[tag_key] = "road"

	else:
		tags["fixme"] = "Add highway tag for %s" % segment['typeVeg']
		message ("  ** No highway tagging - %s %s\n" % (segment['typeVeg'], segment['referanse']))

	# Tunnels and bridges

	medium = ""
	if "medium" in segment['geometri']:
		medium = segment['geometri']['medium']
	elif "medium" in segment:
		medium = segment['medium']

	if medium:
		if medium in ["U", "W", "J"]:
			tags['tunnel'] = "yes"
			tags['layer'] = "-1"

		elif medium == "B":
			tags['tunnel'] = "building_passage"

		elif medium == "L":
			tags['bridge'] = "yes"
			tags['layer'] = "1"

	# Street name

	if "gate" in segment:
		if  segment['typeVeg'] != "Rundkjøring":
			tags['name'] = fix_street_name(segment['gate']['navn'])
#		if tag_key in tags and tags[tag_key] == "service":  # Upgrade street category if name is present (now done through road object "Gate")
#			tags[tag_key] = "unclassified"

	# Information tags for debugging

	if debug:
		extras["DETALJNIVÅ"] = segment['detaljnivå']
		extras["TYPEVEG"] = segment['typeVeg']			

		if lanes:
			extras['FELT'] = " ".join(lanes)

		if medium:
			extras["MEDIUM"] = "#" + medium + " " + medium_types[ medium ]

		if "topologinivå" in segment:
			extras["TOPOLOGINIVÅ"] = segment['topologinivå']

		if ref:
			ref = segment['vegsystemreferanse']
			extras["VEGNUMMER"] = str(ref['vegsystem']['nummer'])
			extras["VEGREFERANSE"] = ref['kortform']
			extras["FASE"] = "#" + ref['vegsystem']['fase'] + " " + road_status[ ref['vegsystem']['fase'] ]
			extras["KATEGORI"] = "#" + ref['vegsystem']['vegkategori'] + " " + road_category[ ref['vegsystem']['vegkategori'] ]['name']

			if "sideanlegg" in ref:
				extras['SIDEANLEGG'] = "%i-%i id:%i" % (ref['sideanlegg']['sideanlegg'], ref['sideanlegg']['sideanleggsdel'], ref['sideanlegg']['id'])
			if "kryssystem" in ref:
				extras['KRYSSYSTEM'] = "%i-%i id:%i" % (ref['kryssystem']['kryssystem'], ref['kryssystem']['kryssdel'], ref['kryssystem']['id'])

	# Return highway type
	if segment['typeVeg'] in ["Enkel bilveg", "Kanalisert veg"]:
		return "Bilveg"
	elif segment['typeVeg'] in ["Gang- og sykkelveg", "Sykkelveg"]:
		return "Sykkelveg"
	else:
		return segment['typeVeg']



# Produce tagging for supported road objects.
# Important note: Each individual segment is not known in this function.
# Updates which depend on each segment is done in the update_tags function below.

def tag_object (object_id, properties, tags):

	if object_id == "595":  # Motorway/motorroad
		if properties['Motorvegtype'] == "Motorveg":
			tags['motorway'] = "yes"  # Dummy to flag new highway class
		elif properties['Motorvegtype'] == "Motortrafikkveg":
			tags['motorroad'] = "yes"

	elif object_id == "821":  # Functional road class
		if municipality_id == "0301" and properties['Vegklasse'] == 4:
			tags['secondary'] = "yes"  # Dummy to flag secondary highway class for Oslo
		elif properties['Vegklasse'] < 6:  # Only class 4 and 5 ?
			tags['tertiary'] = "yes"  # Dummy to flag new highway class below secondary level

	elif object_id == "105":  # Maxspeed
		if "Fartsgrense" in properties: 
			tags['maxspeed'] = str(properties["Fartsgrense"])

	elif object_id == "538":  # Address name
		if "Adressenavn" in properties:  # Used to be "Gatenavn"
			tags['name'] = fix_street_name(properties['Adressenavn'])
			if properties['Sideveg'] != "Ja":  # Not consistently tagged in NVDB (== "Nei")
				tags['mainroad'] = "yes"  # Dummy to flag new highway class instead of residential/service

	elif object_id == "581":  # Tunnels, 1st pass
		if "Navn" in properties:
			tags['tunnel:name'] = properties['Navn'].replace("  "," ").strip()
		if properties['Sykkelforbud'] == "Ja":
			tags['bicycle'] = "no"
			tags['foot'] = "no"

	elif object_id == "67":  # Tunnels, 2nd pass
		tags['tunnel'] = "yes"
		tags['layer'] = "-1"
		if "Navn" in properties and not("tunnel:name" in tags and tags['tunnel:name'] == properties['Navn']):
			tags['tunnel:description'] = properties['Navn'].replace("  "," ").strip()

	if object_id == "66":  # Avalanche protector
		tags['tunnel'] = "avalanche_protector"
		tags['layer'] = "-1"
		if "Navn" in properties:
			tags['tunnel:name'] = properties['Navn'].replace("  "," ").strip()	

	elif object_id == "60":  # Bridge
		tags['bridge'] = "yes"
		tags['layer'] = "1"		
		if "Navn" in properties:
			tags['bridge:description'] = properties['Navn'].replace("  "," ").replace(" Bru", " bru").strip()
		if "Byggverkstype" in properties:
			bridge_type = properties['Byggverkstype'].lower()
			if "hengebru" in bridge_type:
				tags['bridge:structure'] = "suspension"
			if "bue" in bridge_type or "hvelv" in bridge_type:
				tags['bridge:structure'] = "arch"
			elif "fagverk" in bridge_type:
				tags['bridge:structure'] = "truss"
			elif bridge_type in ["klaffebru", "svingbru", "rullebru"]:
				tags['bridge'] = "movable"
				if bridge_type == "klaffebru":
					tags['bridge:movable'] = "bascule"
				elif bridge_type == "svingbru":
					tags['bridge:movable'] = "swing"
				elif bridge_type == "rullebru":
					tags['bridge:movable'] = "retractable"
			elif bridge_type == "flytebru":
				tags['bridge:structure'] = "floating"

	elif object_id == "856":  # Access restriction
		restrictions = {
			'Forbudt for alle kjøretøy': {'motor_vehicle': 'no'},
			'Forbudt for gående': {'foot': 'no'},
			'Forbudt for gående og syklende': {'foot': 'no', 'bicycle': 'no'},
			'Forbudt for lastebil og trekkbil': {'hgv': 'no'},
			'Forbudt for lastebil og trekkbil m unntak': {'hgv': 'permissive'},
			'Forbudt for motorsykkel': {'motorcycle': 'no'},
			'Forbudt for motorsykkel og moped': {'motorcycle': 'no', 'moped': 'no'},
			'Forbudt for motortrafikk': {'motor_vehicle': 'no'},
			'Forbudt for motortrafikk unntatt buss': {'motor_vehicle': 'no', 'bus': 'yes'},
			'Forbudt for motortrafikk unntatt buss og taxi': {'motor_vehicle': 'no', 'psv': 'yes'},
			'Forbudt for motortrafikk unntatt moped': {'motor_vehicle': 'no', 'moped': 'yes'},
			'Forbudt for motortrafikk unntatt spesiell motorvogntype': {'motor_vehicle': 'permissive'},
			'Forbudt for motortrafikk unntatt taxi': {'motor_vehicle': 'no', 'taxi': 'yes'},
			'Forbudt for motortrafikk unntatt varetransport': {'motor_vehicle': 'delivery'},
			'Forbudt for syklende': {'bicycle': 'no'},
			'Forbudt for traktor': {'agricultural': 'no'},
			'Utgår_Gjennomkjøring forbudt': {'motor_vehicle': 'destination'},
			'Utgår_Gjennomkjøring forbudt for lastebil og trekkbil': {'hgv': 'destination'},
			'Utgår_Gjennomkjøring forbudt til veg eller gate': {'motor_vehicle': 'destination'},
			'Motortrafikk kun tillatt for kjøring til eiendommer': {'motor_vehicle': 'destination'},
			'Motortrafikk kun tillatt for kjøring til virksomhet eller adresse': {'motor_vehicle': 'destination'},
			'Motortrafikk kun tillatt for varetransport': {'motor_vehicle': 'delivery'},
			'Motortrafikk kun tillatt for varetransport og kjøring til eiendommer': {'motor_vehicle': 'destination'},
			'Utgår_Sykling mot kjøreretningen tillatt': {'oneway:bicycle': 'no'}
		}
		if "Trafikkreguleringer" in properties:
			if properties['Trafikkreguleringer'].strip() in restrictions:
				tags.update(restrictions[ properties['Trafikkreguleringer'].strip() ])
			else:
				message ("  *** Unknown access restriction: %s\n" % properties['Trafikkreguleringer'])

	elif object_id == "103":  # Speed bump
		if properties['Type'] == "Fartshump":
			tags['traffic_calming'] = "table"  # Mostly long/wide humps

	elif object_id == "22":  # Cattle grid
		tags['barrier'] = "cattle_grid"			

	elif object_id == "47":  # Passing place
		if properties['Bruksområde'] == "Møteplass":
			tags['highway'] = "passing_place"

	elif object_id in ["607", "23"]:  # Barrier
		barriers = {
			'Heve-/senkebom': 'lift_gate',
			'Utgår_Heve-/senkebom, ensidig': 'lift_gate',
			'Utgår_Heve-/senkebom, tosidig': 'lift_gate',
			'Svingbom': 'swing_gate',
			'Utgår_Svingbom, enkel': 'swing_gate',
			'Utgår_Svingbom, dobbel': 'swing_gate',
			'Stolpe/pullert/kjegle': 'bollard',
			'Rørgelender': 'cycle_barrier',
			'Steinblokk': 'block',
			'Betongblokk': 'jersey_barrier',
			'Bussluse': 'bus_trap',
			'Annen type vegbom/sperring': 'gate',
			'Låst bom': 'yes',
#			'Utgår_Trafikkavviser': 'bollard',
#			'Bilsperre': 'gate',
		}
		if (properties['Bruksområde'] == "Gang-/sykkelveg, sluse"
				and (properties['Type'] == "Annen type vegbom/sperring" or "Type" not in properties)):
			tags['barrier'] = "swing_gate"
		elif properties['Bruksområde'] not in ["Tunnel", "Bomstasjon", "Ferjekai", "Jernbane"]:
			if properties['Type'] in barriers:
				tags['barrier'] = barriers[ properties['Type'] ]
			else:
				if "Type" in properties:
					message ("  *** Unknown barrier type: %s\n" % properties['Type'])
				tags['barrier'] = "yes"
			if properties['Bruksområde'] == "Høyfjellsovergang":
				tags['access'] = "yes"
				if "Stedsnavn" in properties:
					tags['name'] = properties['Stedsnavn']

	elif object_id == "174":  # Pedestrian crossing
		tags['highway'] = "crossing"		
		if properties['Trafikklys'] == "Ja":
			tags['crossing'] = "traffic_signals"
		elif properties['Markering av striper'] == "Malte striper":
			tags['crossing'] = "uncontrolled"
		elif properties['Markering av striper'] == "Ikke striper":
			tags['crossing'] = "unmarked"
		if properties ["Trafikkøy"] == "Ja":
			tags['crossing:island'] = "yes"

	elif object_id == "100":  # Railway crossing
		if "I plan" in properties['Type']:
			tags['railway'] = "level_crossing"
			if "uten lysregulering og bommer" in properties['Type']:
				tags['crossing'] = "uncontrolled"
			else:
				if "uten bommer" not in properties['Type'] or "grind" in properties['Type']:
					tags['crossing:barrier'] = "yes"
				if "lysregulert" in properties['Type']:
					tags['crossing:light'] = "yes"  # crossing = traffic_light ?


	elif object_id == "89":  # Traffic signal
		if properties['Bruksområde'] == "Vegkryss":  # ,"Skyttelsignalanlegg"
			tags['highway'] = "traffic_signals"
		elif properties['Bruksområde'] == "Gangfelt":
			tags['highway'] = "crossing"
			tags['crossing'] = "traffic_signals"		

	elif object_id == "241":  # Surface
		if "asfalt" not in properties['Massetype'].lower():
			if "betong" in properties['Massetype'].lower():
				tags['surface'] = "concrete"
			elif "grus" in properties['Massetype'].lower():
				tags['surface'] = "gravel"
			elif properties['Massetype'] == "Brostein/Gatestein":
				tags['surface'] = "sett"
			elif properties['Massetype'] == "Belegningsstein":
				tags['surface'] = "paving_stones"
			elif properties['Massetype'] == "Tre (bru)":
				tags['surface'] = "wood"
			elif properties['Massetype'] == "Stålgitter (bru)":
				tags['surface'] = "metal"
		else:
			tags['surface'] = "asphalt"

	elif object_id == "591":  # Maxheight
		if "Skilta høyde" in properties:
			tags['maxheight'] = str(properties['Skilta høyde'])

	elif object_id == "904":  # Maxweight/maxlength
		if "tonn" in properties['Bruksklasse'] and "50 tonn" not in properties['Bruksklasse']:
			tags['maxweight'] = properties['Bruksklasse'][-7:-5]  # "xx tonn"
		if properties['Maks vogntoglengde'] in ['12,40', '15,00']:
			tags['maxlength'] = properties['Maks vogntoglengde'].replace(",", ".")

	elif object_id == "64":  # Ferry terminal
		tags['amenity'] = "ferry_terminal"
		if "Navn" in properties:
			tags['name'] = properties['Navn'].replace("Fk","").replace("Kai","").replace("  "," ").strip()

	elif object_id == "770":  # Ferry route
		if "Navn" in properties:
			tags['name'] = properties['Navn'].strip()

	elif object_id == "37":  # Motorway junction
		if "Planskilt kryss" in properties['Type']:
			tags['highway'] = "motorway_junction"
			if "Kryssnummer" in properties:
				tags['ref'] = str(properties['Kryssnummer'])
			if "Navn" in properties:
				tags['name'] = properties['Navn'].replace("  ", " ").strip()

	elif object_id == "96":  # Sign
		if "Trafikk" in properties['Ansiktsside, rettet mot']:
			if properties['Skiltnummer'] == "204 - Stopp":  # 7643
				tags['highway'] = "stop"
			elif properties['Skiltnummer'] == "202 - Vikeplikt":  # 7642
				tags['highway'] = "give_way"
			elif properties['Skiltnummer'] == "306.6 - Forbudt for syklende":  # 7655
				tags['traffic_sign'] = "NO:306.6"
				tags['bicycle'] = "no"
			elif properties['Skiltnummer'] == "306.7 - Forbudt for gående":  # 7656
				tags['traffic_sign'] = "NO:306.7"
				tags['foot'] = "no"
			elif properties['Skiltnummer'] == "306.8 - Forbudt for gående og syklende":  # 7657
				tags['traffic_sign'] = "NO:306.8"
				tags['bicycle'] = "no"
				tags['foot'] = "no"

	elif object_id == "107":  # Weather restriction
		if "Vinterstengt, fra dato" in properties or "Vinterstengt, til dato" in properties:
			tags['snowplowing'] = "no"
			if "Vinterstengt, fra dato" in properties and "Vinterstengt, til dato" in properties:
				tags['motor_vehicle:conditional'] = "no @ %s-%s" % (calendar.month_abbr[int(properties['Vinterstengt, fra dato'][0:2])], \
																	calendar.month_abbr[int(properties['Vinterstengt, til dato'][0:2])])
			if "Tilleggsinformasjon" in properties:
				tags['description'] = properties['Tilleggsinformasjon'].replace("  "," ")

	elif object_id == "291":  # Hazard
		tags['hazard'] = "animal_crossing"
		if properties['Art'] == "Hjort":
			tags['species:en'] = "deer"
		elif properties['Art'] == "Elg":
			tags['species:en'] = "moose"
		elif properties['Art'] == "Rein":
			tags['species:en'] = "raindeer"
		elif properties['Art'] == "Rådyr":
			tags['species:en'] = "venison"

	elif object_id == "777":  # Scenic route
		if properties['Status'] != "Framtidig turistveg":
			tags['scenic'] = "yes"
			tags['scenic:name'] = properties['Navn']

	elif object_id == "922":  # Highway class undetermined
		if properties['Foreslått endring'] and properties['Foreslått endring'] != "Annen endring":
			tags['note'] = "Foreslått " + properties['Foreslått endring'].lower()
		else:
			tags['note'] = "Foreslått endring av veiklasse"

	elif object_id == "923":  # Diversion
		tags['note'] = "Beredskapsvei"  # Further tagging in update_tags function

	elif object_id == "924":  # Service road
		tags['note'] = "Servicevei"  # Further tagging in update_tags function



# Update tags in segment, including required corrections for motorway, maxspeed and street name
# This is the only place to make road object tagging dependent on earlier basic highway tagging based on road reference

def update_tags (segment, tags, direction):

	# Get right key, if highway
	if "construction" in segment['tags']:
		highway = "construction"
	elif "proposed" in segment['tags']:
		highway = "proposed"
	else:
		highway = "highway"

	# Please note only if/elif below due to catch-all at the end

	# Keep name and unclassified update together
	if "name" in tags or "mainroad" in tags:

		# No street name for cycleways/footways and roundabouts
		if "name" in tags and not ("junction" in segment['tags'] and segment['tags']['junction'] == "roundabout"):
			segment['tags']['name'] = tags['name']

		# Unclassified 
		if "mainroad" in tags:
			if highway in segment['tags'] and segment['tags'][highway] == "service":  # , "residential"]:
				segment['tags'][ highway ] = "unclassified"

	# Apply secondary tag in Oslo
	elif "secondary" in tags:
		if highway in segment['tags'] and segment['tags'][ highway ] in ["service", "residential", "unclassified"]:
			segment['tags'][ highway ] = "secondary"

	# Apply tertiary tag to important roads
	elif "tertiary" in tags:
		if highway in segment['tags'] and segment['tags'][ highway ] in ["service", "residential", "unclassified"]:
			segment['tags'][ highway ] = "tertiary"

	# Change highway type to motorway if given
	elif "motorway" in tags:
		if highway in segment['tags']:
			if "link" in segment['tags'][ highway ]:
				segment['tags'][ highway ] = "motorway_link"
			else:
				segment['tags'][ highway ] = "motorway"

	# No maxspeed for service, cycleways and footways.
	# Maxspeeds may be different for each direction.
	elif "maxspeed" in tags:
		if not ("highway" in segment['tags'] and segment['tags']['highway'] in ["unclassified", "service", "cycleway", "footway"]):
			if direction and "oneway" not in segment['tags']:
				if "maxspeed" not in segment['tags']:
					segment['tags']['maxspeed:' + direction] = tags['maxspeed']
					if ("maxspeed:forward" in segment['tags'] and "maxspeed:backward" in segment['tags']
							and segment['tags']['maxspeed:forward'] == segment['tags']['maxspeed:backward']):
						del segment['tags']['maxspeed:forward']
						del segment['tags']['maxspeed:backward']
						segment['tags']['maxspeed'] = tags['maxspeed']
			else:
				segment['tags']['maxspeed'] = tags['maxspeed']
				for key in ["maxspeed:forward", "maxspeed:backward"]:
					if key in segment['tags']:
						del segment['tags'][ key ]

	# Only apply extra tunnel and bridge tags if tunnel/bridge already identified (from 'medium' attribute in road network)
	elif "tunnel" in tags or "bridge" in tags:
		if "tunnel" in tags and "tunnel" in segment['tags'] or "bridge" in tags and "bridge" in segment['tags'] or function == "vegobjekt":
			segment['tags'].update(tags)

	# Max weight for bridges only. 	Max length tags for tertiary and above road classes only
	elif "maxlength" in tags or "maxweight" in tags:
		if "maxlength" in tags and "highway" in segment['tags'] and segment['tags']['highway'] in \
				['motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link']:
			new_tags = {
				'maxlength': tags['maxlength']
			}
			segment['tags'].update(new_tags)

		if "maxweight" in tags and "bridge" in segment['tags']:
			new_tags = {
				'maxweight': tags['maxweight']
			}
			segment['tags'].update(new_tags)

	# Deviations for highways only, not ferries
	elif "note" in tags and tags['note'] == "Beredskapsvei":
		if "route" in segment['tags']:
			segment['tags']['note'] = "Beredskapsferje"
#			del segment['tags']['route']
		else:
			segment['tags'][ highway ] = "service"
			segment['tags']['motor_vehicle'] = "no"
			segment['tags']['note'] = "Beredskapsvei"
			if "ref" in segment['tags']:
				del segment['tags']['ref']

	# Service road
	elif "note" in tags and tags['note'] == "Servicevei":
		segment['tags'][ highway ] = "service"
		segment['tags']['motor_vehicle'] = "no"
		segment['tags']['note'] = "Servicevei"
		if "ref" in segment['tags']:
			del segment['tags']['ref']

	else:
		segment['tags'].update(tags)



# Create new node to be used for intersections between ways
# Returns generated node id

def create_new_node (node_id, point, way_id_set):

	global master_node_id

	if not isinstance(point, list):
		message ("  *** Not list: %s\n" % str(point))

	if not node_id:
		master_node_id -= 1
		node_id = str(master_node_id) 
	if node_id not in nodes:
		nodes[node_id] = {
			'point': point,
			'ways': way_id_set,  # Set
			'tags': {},
			'extras': {},
			'break': False
			}
	else:
		nodes[node_id]['ways'].update(way_id_set)  # Set
		nodes[node_id]['tags'].update(point[2])

	return node_id



# Generate list of [lat,lon,tags] coordinates from wkt

def unpack_wkt (wkt):

	geometry = []

	wkt_points = wkt.split(", ")

	for point in wkt_points:
		coordinate = point.lstrip("(").rstrip(")").split(" ")
		geometry.append([float(coordinate[0]), float(coordinate[1]), {}])

	return geometry



# Generate geometry from wkt

def process_geometry (wkt):

	# Split "multi" wkts into separate individual wkts

	geometry = []
	start = wkt.find("(")
	geometry_type = wkt[:start - 1]
	wkt = wkt[start + 1:-1]
	wkt_split = wkt.split("), (")

	for wkt_part in wkt_split:
		wkt_part = wkt_part.lstrip("(").rstrip(")")
		geometry_list = unpack_wkt(wkt_part)
		geometry.append(geometry_list)

	if "POINT" in geometry_type:  # ["POINT", "POINT Z", "MULTIPOINT", "MULTIPOINT Z"]
		return (geometry, "point")
	else:
		return (geometry, "line")



# Remove nodes if node distance too small

def fix_geometry (line):

	i = 0
	previous_node = line[0]
	while i < len(line) - 2:
		i += 1
		if compute_distance(previous_node, line[i]) < fix_margin:
			del line[i]
			i -= 1
		else:
			previous_node = line[i]

	if len(line) > 2 and compute_distance(line[-2], line[-1]) < fix_margin:
		del line[-2]

	if len(line) < 2:
		message ("  *** Less than two coordinates in line\n")
#	elif len(line) == 2 and line[0] == line[1] or compute_distance(line[0], line[1]) == 0:
#		message ("  *** Zero length line\n")



# Clip segment into two segments at given position

def clip_segment (segment, clip_position):

	global master_segment_id

	if clip_position == segment['parent_start'] or clip_position == segment['parent_end']:
		message ("  *** Too short clipping: %s %f\n" % (segment['id'], clip_position))

	clip_length = (clip_position - segment['parent_start']) * segment['length'] / (segment['parent_end'] - segment['parent_start'])  # In meters

	previous_node = segment['geometry'][0]
	node = segment['geometry'][1]
	previous_length = 0.0
	node_length = compute_distance(previous_node, node)

	j = 0
	while j < len(segment['geometry']) - 2 and previous_length + node_length < clip_length:
		j += 1
		previous_length += node_length
		previous_node = node
		node = segment['geometry'][j+1]
		node_length = compute_distance(previous_node, node)
		if node_length == 0.0 or node[0:2] == previous_node[0:2]:
			message ("  *** Two equal nodes\n")

	factor = (clip_length - previous_length) / node_length
	new_node = [previous_node[0] + factor * (node[0] - previous_node[0]), \
				previous_node[1] + factor * (node[1] - previous_node[1]), \
				{} ]
	
	if new_node[0:2] == segment['geometry'][-1][0:2] or segment['length'] == clip_length:
		message ("  *** New node equal to last node\n")
	if new_node[0:2] == segment['geometry'][0][0:2]  or clip_length == 0:
		message ("  *** New node equal to last node\n")

	master_segment_id -= 1
	new_segment_id = str(master_segment_id)
	node_id = create_new_node("", new_node, set([segment['id'], new_segment_id]))

	new_segment = copy.deepcopy(segment)
	segment['geometry'] = segment['geometry'][0:j+1] + [new_node]
	new_segment['geometry'] = [new_node] + new_segment['geometry'][j+1:]

	new_segment['id'] = new_segment_id
	new_segment['parent_start'] = clip_position
	new_segment['start_node'] = node_id
	new_segment['length'] = new_segment['length'] - clip_length
	if debug:
		new_segment['extras']['KLIPP'] = "Ja"

	segments[new_segment_id] = new_segment
	sequences[ segment['sequence'] ].append(new_segment_id)
	parents[ segment['parent'] ].append(new_segment_id)

	segment['parent_end'] = clip_position
	segment['end_node'] = node_id
	segment['length'] = clip_length
	if debug:
		segment['extras']['KLIPP'] = "Ja"

	nodes[ new_segment['end_node'] ]['ways'].remove(segment['id'])
	nodes[ new_segment['end_node'] ]['ways'].add(new_segment_id)

	return new_segment



# Identify relevant segments and upate tags
# Clip segment if necessary. New clipped segments are appended at the end of sequence list

def update_segments_line (parent_sequence_id, tag_start, tag_end, direction, new_tags, new_extras):

	# Additional tags for tunnels and bridges, which already have 'tunnel' and 'bridge' tags
	# Problem not solved: Separate south/northbound bridges in certain cases

	if "tunnel" in new_tags or "bridge" in new_tags:
		for segment_id in parents[parent_sequence_id][:]:
			segment = segments[ segment_id ]
			if ("tunnel" in new_tags and "tunnel" in segment['tags'] or "bridge" in new_tags and "bridge" in segment['tags']) and \
					(not direction or segment['reverse'] == (direction == "backward")):

				margin = (segment['parent_end'] - segment['parent_start']) / segment['length'] * node_margin  # Meters
				if tag_start < segment['parent_start'] + margin and segment['parent_end'] - margin < tag_end or \
						segment['parent_start'] + margin < tag_start < segment['parent_end'] - margin or \
						segment['parent_start'] + margin < tag_end < segment['parent_end'] - margin:
					update_tags(segment, new_tags, "")
					segment['extras'].update(new_extras)

	else:
#		if direction and "maxspeed" not in new_tags and "surface" not in new_tags and "maxheight" not in new_tags:
#			message ("  *** Tag with direction %s: %s\n" % (direction, str(new_tags)))
		for segment_id in parents[parent_sequence_id][:]:
			segment = segments[ segment_id ]

			# Direction of object (if given) must be same as direction of highway (if oneway)
			if not(direction and "oneway" in segment['tags'] and segment['reverse'] == (direction == "forward")):

				margin = (segment['parent_end'] - segment['parent_start']) / segment['length'] * segment_margin  # Meters
				if tag_start < segment['parent_start'] + margin and segment['parent_end'] - margin < tag_end:
					update_tags(segment, new_tags, direction)
					segment['extras'].update(new_extras)

				elif segment['parent_start'] + margin < tag_start and tag_end < segment['parent_end'] - margin:
					new_segment = clip_segment (segment, tag_start)
					clip_segment (new_segment, tag_end)
					update_tags(new_segment, new_tags, direction)
					new_segment['extras'].update(new_extras)

				elif segment['parent_start'] + margin < tag_start < segment['parent_end'] - margin:
					new_segment = clip_segment (segment, tag_start)
					update_tags(new_segment, new_tags, direction)
					new_segment['extras'].update(new_extras)

				elif segment['parent_start'] + margin < tag_end < segment['parent_end'] - margin:
					new_segment = clip_segment (segment, tag_end)
					update_tags(segment, new_tags, direction)
					segment['extras'].update(new_extras)



# Insert node at given position in way
# Snap to start or end node if possible

def insert_node (segment, insert_position):

	position_length = (insert_position - segment['parent_start']) * segment['length'] / (segment['parent_end'] - segment['parent_start'])  # In meters

	if position_length < point_margin:  # Snap to first node
		return 0  
	elif segment['length'] - position_length < point_margin:  # Snap to last node
		return len(segment['geometry']) - 1

	previous_node = segment['geometry'][0]
	node = segment['geometry'][1]
	previous_length = 0.0
	node_length = compute_distance(previous_node, node)

	j = 0

	while j < len(segment['geometry']) - 2 and previous_length + node_length < position_length:
		j += 1
		previous_length += node_length
		previous_node = node
		node = segment['geometry'][j+1]
		node_length = compute_distance(previous_node, node)
		if node_length == 0.0 or node[0:2] == previous_node[0:2]:
			message ("  *** Two equal nodes\n")

	# Snap to tagged or closest node

	if segment['geometry'][j][2] and position_length - previous_length < point_margin \
			or segment['geometry'][j+1][2] and previous_length + node_length - position_length < point_margin:
		if previous_length + node_length - position_length < position_length - previous_length and segment['geometry'][j+1][2] or not segment['geometry'][j][2]:
			return j + 1  # Next node closest
		else:
			return j  # Previous node closest

	elif position_length - previous_length < node_margin or previous_length + node_length - position_length < node_margin:
		if previous_length + node_length - position_length < position_length - previous_length:
			return j + 1  # Next node closest
		else:
			return j  # Previous node closest

	else:
		factor = (position_length - previous_length) / node_length
		new_node = [previous_node[0] + factor * (node[0] - previous_node[0]), \
					previous_node[1] + factor * (node[1] - previous_node[1]), \
					{} ]
		segment['geometry'] = segment['geometry'][0:j+1] + [new_node] + segment['geometry'][j+1:]
		segment['insert'] = True

		return j + 1



# Insert new node (if necessary) and update tags in all segments with given super/parent segment

def update_segments_point (parent_sequence_id, tag_position, new_tags, new_extras): 

	for segment_id in parents[parent_sequence_id]:
		segment = segments[segment_id]

		if segment['parent_start'] <= tag_position <= segment['parent_end']: # and (not side or side == "H" and not segment['reverse'] or side == "V" and segment['reverse']):
			position = tag_position

			if "highway" in new_tags and new_tags['highway'] == "traffic_signals":  # Traffic signals to snap to closest start/end of segment
				if tag_position - segment['parent_start'] < segment['parent_end'] - tag_position:
					position = segment['parent_start']
				else:
					position = segment['parent_end']

			node_index = insert_node(segment, position)
			segment['geometry'][node_index][2].update(new_tags)
			if debug:
				segment['geometry'][node_index][2].update(new_extras)



# Travers road network to find shortest driving route to one of target segments
# Return distance and route of segments

def traverse_network (segment_id, from_node_id, route, distance, target_segments, max_distance):

	debug_traverse = False

	if debug_traverse:
		message ("  Traverse: %s %s %s %fm\n" % (segment_id, from_node_id, route, distance))

	segment = segments[ segment_id ]

	# Segment already travelled, circular route
	if segment_id in route:
		if debug_traverse:
			message ("    Circular\n")
		return (False, distance, route)

	# Segment not permitted for cars
	if segment['highway'] not in ["Bilveg", "Rampe", "Rundkjøring", "Gatetun"] and \
			not ("motor_vehicle" in segment['tags'] and segment['tags']['motor_vehicle'] != "no") or \
			"motor_vehicle" in segment['tags'] and segment['tags']['motor_vehicle'] == "no" or \
			"highway" not in segment['tags'] or "construction" in segment['tags']:
		if debug_traverse:
			message ("    No cars, %s\n" % segment['highway'])
		return (False, distance, route)

	# Oneway, direction of travel not permitted
	if "oneway" in segment['tags'] and (segment['reverse'] and segment['start_node'] == from_node_id or \
			not segment['reverse'] and segment['end_node'] == from_node_id):
		if debug_traverse:
			message ("    Oneway\n")
		return (False, distance, route)

	# Direction of travel not permitted in that direction
	if "motor_vehicle:forward" in segment['tags'] and (segment['reverse'] and segment['end_node'] == from_node_id or \
			not segment['reverse'] and segment['start_node'] == from_node_id) or \
		"motor_vehicle:backward" in segment['tags'] and (segment['reverse'] and segment['start_node'] == from_node_id or \
			not segment['reverse'] and segment['end_node'] == from_node_id):
		if debug_traverse:
			message ("    No cars in that direction - %s\n" % segment_id)
		return (False, distance, route)

	new_route = copy.deepcopy(route)
	if route:
		new_route.append(from_node_id)
	new_route.append(segment_id)

  	# Target found, return route including target segment (still need via_node testing)
	if segment_id in target_segments:
		if debug_traverse:
			message ("    Found\n")
		return (True, distance, new_route)

	# Too long route
	if route:
		distance += segment['length']
	if distance > max_distance or len(new_route) > 2 * max_travel_depth:
		if debug_traverse:
			message ("    Too long\n")
		return (False, distance, route)

	if segment['start_node'] != from_node_id:
		next_node_id = segment['start_node']
	else:
		next_node_id = segment['end_node']

	# Recursively travers network for next route alternatives

	best_distance = max_distance
	best_route = []

	if debug_traverse:
		message ("    Node ways: %s\n" % nodes[ next_node_id ]['ways'])

	for next_segment_id in nodes[ next_node_id ]['ways']:
		if next_segment_id != segment_id:
			test_result, test_distance, test_route = \
				traverse_network (next_segment_id, next_node_id, new_route, distance, target_segments, best_distance)
			if test_result and test_distance < best_distance:  # and via_node_id in test_route 
				best_route = test_route
				best_distance = test_distance
				if debug_traverse:
					message ("    New best route: %s %fm\n" % (best_route, best_distance))

	if best_route:
		return (True, best_distance, best_route)
	else:
		return (False, distance, route)



# Create turn restriction

def create_turn_restriction (restriction, restriction_id):

	via_node_id = str(restriction['nodeid'])
	if via_node_id not in nodes:
		via_node_id = None

	# Locate potential from and to segments

	from_segments = []
	to_segments = []

	if restriction['startpunkt']['veglenkesekvensid'] in parents:
		for segment_id in parents[ restriction['startpunkt']['veglenkesekvensid'] ]:
			segment = segments[segment_id]
			if segment['parent_start'] <= restriction['startpunkt']['relativPosisjon'] <= segment['parent_end']:
				from_segments.append(segment_id)
	elif restriction['startpunkt']['veglenkesekvensid'] in sequences:
		for segment_id in sequences[ restriction['startpunkt']['veglenkesekvensid'] ]:
			segment = segments[segment_id]
			if segment['sequence_start'] <= restriction['startpunkt']['relativPosisjon'] <= segment['sequence_end']:
				from_segments.append(segment_id)

	if not from_segments:
		return


	if restriction['sluttpunkt']['veglenkesekvensid'] in parents:
		for segment_id in parents[ restriction['sluttpunkt']['veglenkesekvensid'] ]:
			segment = segments[segment_id]
			if segment['parent_start'] <= restriction['sluttpunkt']['relativPosisjon'] <= segment['parent_end']:
				to_segments.append(segment_id)
	elif restriction['sluttpunkt']['veglenkesekvensid'] in sequences:
		for segment_id in sequences[ restriction['sluttpunkt']['veglenkesekvensid'] ]:
			segment = segments[segment_id]
			if segment['sequence_start'] <= restriction['sluttpunkt']['relativPosisjon'] <= segment['sequence_end']:
				to_segments.append(segment_id)

	if not to_segments:
		return

	# Travel network to find shortest route between from and to segments

	best_distance = 200.0  # meters
	best_route = []

	for next_segment_id in from_segments:
		segment = segments[ next_segment_id ]
		for next_node in [segment['start_node'], segment['end_node']]:
			test_result, test_distance, test_route = \
				traverse_network (next_segment_id, next_node, [], 0.0, to_segments, best_distance)
			if test_result and test_distance < best_distance:
				best_route = test_route
				best_distance = test_distance

	if not best_route:
		return

	# Store restriceion for later output
	# Determine via node based on sudden change in bearing. If no sudden change, use NVDB given node. If no NVDB node pick arbitray middel node in route.
	# Determine restriction type based on change in bearing at via node

	new_restriction = {
		'from_segment': best_route[0],  # Backup: First way in route
		'to_segment': best_route[-1],  # Backup: Last way in route
		'via_node': via_node_id,  # Backup: Node given by NVDB
		'type': "no_straight_on",  # Backup if no sudden change in bearing along route
		'fixme': True
	}

	for i in range(1, len(best_route) - 1, 2):
		angle = compute_junction_angle(best_route[i-1], best_route[i+1])
		if abs(angle) > angle_margin:
			new_restriction['from_segment'] = best_route[i-1]
			new_restriction['to_segment'] = best_route[i+1]
			via_node_id = best_route[i]
			new_restriction['via_node'] = via_node_id
			new_restriction['fixme'] = False
			if angle < -135 or angle < -90 and segments[ new_restriction['from_segment'] ]['parent'] == segments[ new_restriction['to_segment'] ]['parent']:  # -150
				new_restriction['type'] = "no_u_turn"
			elif angle < 0:  # < 45
				new_restriction['type'] = "no_left_turn"
			else:  # > 45
				new_restriction['type'] = "no_right_turn"
			break

	if not via_node_id:
		i = len(best_route) // 2
		if i % 2 == 0:
			i += 1
		via_node_id = best_route[i]
		new_restriction['via_node'] = via_node_id

	if len(best_route) == 3:
		new_restriction['fixme'] = False

	# Check if identical restriction already stored

	found = False
	for turn_restriction_id, turn_restriction in iter(turn_restrictions.items()):
		if turn_restriction == new_restriction:
			found = True
			break

	if not found:
		turn_restrictions[ restriction_id ] = new_restriction
		nodes[ via_node_id ]['break'] = True



# Fetch road objects of given type for municipality from NVDB api
# Also update relevant segments with new tagging from objects
# In debug mode, saves input data to file

def get_road_object (object_id, **kwargs):

	global api_calls

	message("Merging object type #%s %s..." % (object_id, object_types[object_id]))

	object_url = server + "vegobjekter/" + object_id + "?inkluder=metadata,egenskaper,lokasjon&alle_versjoner=false&srid=wgs84"
	if municipality:
		object_url += "&kommune=" + municipality_id
		if "property" in kwargs:
			object_url += "&egenskap=" + kwargs['property']
		if len(municipality_id) == 2:
			object_url = object_url.replace("kommune=", "fylke=")
			if municipality_id == "00":
				object_url = object_url.replace("fylke=00", "fylke=" + ",".join(counties))
	elif url_bbox:
		object_url += "&" + url_bbox

	returned = 1
	total_returned = 0
	objects = []
#	object_name = ""

	# Loop until no more pages to fetch

	while returned> 0:
#		if api_calls % 50 == 0:
#			time.sleep(1)

#		request = urllib.request.Request(object_url, headers=request_headers)
#		file = open_url(request)  #urllib.request.urlopen(request)
#		data = json.load(file)
#		file.close()

		data = load_data(object_url)
		api_calls += 1

		for road_object in data['objekter']:
			properties = Properties({})
			tags = {}
			extras = {}
			if debug:
				extras['ID'] = str(road_object['id']) 
			locations = []
			associated_tunnels = []

			for attribute in road_object['egenskaper']:
				if "verdi" in attribute:
					properties[attribute['navn']] = attribute['verdi']

					key = "VEGOBJEKT_%s_%s" %(object_id, attribute['navn'].replace(" ","_").replace(".","").replace(",","").upper())
					value = attribute['verdi']
					if object_tags or debug:
						extras[key] = "%s" % value

				if attribute['navn'] == "Liste av lokasjonsattributt":
					locations = attribute['innhold']

				elif attribute['navn'] in ["PunktTilknytning", "SvingTilknytning"]:
					locations = [attribute]

				elif attribute['navn'] == "Assosierte Tunnelløp":
					associated_tunnels = attribute['innhold']

			# Add tags from stored tunnels (pass 2)
			if object_id == "67" and road_object['id'] in tunnels:
				tags.update(tunnels[ road_object['id'] ]['tags'])

			tag_object(object_id, properties, tags)

			# Update all connected tunnel segments (pass 1)
			if object_id == "581":
				for tunnel in associated_tunnels:
					tunnels[ tunnel['verdi'] ] = {
						'tags': tags,
						'extras': extras
					}

			# Store turn restrictions for output later
			elif object_id == "573" and locations:
				create_turn_restriction (locations[0], road_object['id'])

			elif tags:
				if object_id == "47":  # Meeting place
					for i, location in enumerate(locations):
						if location['stedfestingstype'] == "Linje":
							locations[i]['stedfestingstype'] = "Punkt"
							locations[i]['sideposisjon'] = "M"
							locations[i]['relativPosisjon'] = (location['startposisjon'] + location['sluttposisjon']) * 0.5

				elif object_id == "89" and locations[0]['stedfestingstype'] == "Linje":  # Traffic signal
					if len(locations) % 2 == 0:
						mid_location = copy.deepcopy(locations[len(locations) // 2 - 1])
						if "retning" not in mid_location or mid_location['retning'] == "MED":
							mid_location['relativPosisjon'] = mid_location['sluttposisjon']
						else:
							mid_location['relativPosisjon'] = mid_location['startposisjon']
					else:
						mid_location = copy.deepcopy(locations[len(locations) // 2])
						mid_location['relativPosisjon'] = (mid_location['startposisjon'] + mid_location['sluttposisjon']) * 0.5

					mid_location['stedfestingstype'] = "Punkt"
					mid_location['sideposisjon'] = "M"
					locations = [ mid_location ]


				for location in locations:
					if location['veglenkesekvensid'] in parents:
						if location['stedfestingstype'] == "Linje":
							if location['startposisjon'] != location['sluttposisjon']:
								if location['kjørefelt']:
									direction, code = get_direction(location['kjørefelt'])
								else:
									direction = ""
								update_segments_line (location['veglenkesekvensid'], location['startposisjon'], location['sluttposisjon'],
														direction, tags, extras)
#							else:
#								message ("  *** Equal start and end positions in location - %i\n" % road_object['id'])

						# For points, only accept "M" positions
						elif location['stedfestingstype'] == "Punkt" and ("sideposisjon" not in location or location['sideposisjon'] == "M" or object_id == "96"):
							update_segments_point (location['veglenkesekvensid'], location['relativPosisjon'], tags, extras)
#					else:
#						message ("  *** Road object sequence %i not found in road network\n" % location['veglenkesekvensid'] )

#			object_name = "'%s'" % road_object['metadata']['type']['navn']

		objects += data['objekter']

		returned = data['metadata']['returnert']
		object_url= data['metadata']['neste']['href']
		total_returned += returned

	message("  %i objects\n" % total_returned)

	if debug:
		debug_file = open("nvdb_vegobjekt_%s_input.json" % object_id, "w")
		debug_file.write(json.dumps(objects, indent=2, ensure_ascii=False))
		debug_file.close()



# Create tuple for hashing segments during network simplification

def get_hash(segment):

	if not segment['vegsystemreferanse']:
		return None

	ref = segment['vegsystemreferanse']

	if "nummer" in ref['vegsystem'] and ref['vegsystem']['nummer'] < 90000:
		if "strekning" in ref and "delstrekning" in ref['strekning'] and segment['typeVeg'] != "Rundkjøring":
			return (ref['vegsystem']['vegkategori'], ref['vegsystem']['fase'], ref['vegsystem']['nummer'], ref['strekning']['strekning'], ref['strekning']['delstrekning'])
		else:
			return (ref['vegsystem']['vegkategori'], ref['vegsystem']['fase'], ref['vegsystem']['nummer'])
	elif "gate" in segment:
		return (ref['vegsystem']['vegkategori'], ref['vegsystem']['fase'], segment['gate']['navn'])
	else:
		return (ref['vegsystem']['vegkategori'], ref['vegsystem']['fase'])



# Generate tagging for road network segment and store in network data structure

def process_road_network (segment):

	if segment['detaljnivå'] != "Vegtrase" and \
			("vegsystemreferanse" not in segment or "vegsystem" not in segment['vegsystemreferanse'] or segment['vegsystemreferanse']['vegsystem']['fase'] != "F"):

		tags = {}
		extras = {}
		segment_id = segment['referanse']

		# Reverse way if backwards one way street

		if "superstedfesting" in segment and "kjørefelt" in segment['superstedfesting']:
			lanes = segment['superstedfesting']['kjørefelt']
			meter_direction = segment['superstedfesting']['retning']
		elif "feltoversikt" in segment:
			lanes = segment['feltoversikt']
			if "strekning" in segment['vegsystemreferanse']:
				meter_direction = segment['vegsystemreferanse']['strekning']['retning']
			else:
				meter_direction = ""
		else:
			lanes = []
			meter_direction = ""

		# Determine if way needs to reverse based on even first lane code

		reverse_geometry = False
		if lanes:
			direction, code = get_direction(lanes[0])
			reverse_geometry = (direction == "backward")

		geometry, geometry_type = process_geometry (segment['geometri']['wkt'])
		geometry = geometry[0]

		if len(geometry) < 2: # or len(geometry) == 2 and geometry[0] == geometry[1] or segment['lengde'] == 0:
			message ("  *** Zero length segment excluded - %s\n" % segment_id)
			return

#		if segment['lengde'] < node_margin:
#			message ("  *** Very short segment %.2fm - %s\n" % (segment['lengde'], segment['referanse']))

		fix_geometry(geometry)

		highway_type = tag_highway(segment, lanes, tags, extras)
		ref_tuple = get_hash(segment)

		# Store information tags for debugging

		if debug:
			extras['ID'] = segment_id
			extras['TYPE'] = segment['type']
			extras['SEKVENS'] = str(segment['veglenkesekvensid'])
			extras['NODER'] = "%s %s" % (segment['startnode'], segment['sluttnode'])			

			if "superstedfesting" in segment:
				parent = segment['superstedfesting']
				extras['STED_SUPER'] = "%f-%f@%i %s %s" % (parent['startposisjon'], parent['sluttposisjon'], parent['veglenkesekvensid'], parent['retning'], parent['sideposisjon'])
				extras['SEKVENS_SUPER'] = str(parent['veglenkesekvensid'])

			if reverse_geometry:
				extras['REVERSERT'] = "Ja"

			ref = segment['vegsystemreferanse']
			if ref:
				if "strekning" in ref:
					extras['STED_SEGMENT'] = "%s %s (%.2fm)" % (segment['kortform'], ref['strekning']['retning'], segment['lengde'])
					if "adskilte_løp" in ref['strekning'] and ref['strekning']['adskilte_løp'] != "Nei":
						extras['ADSKILTE_LØP'] = "%s %s" % (ref['strekning']['adskilte_løp'], ref['strekning']['adskilte_løp_nummer'])
				else:
					extras['STED_SEGMENT'] = "%s (%.2fm)" % (segment['kortform'], segment['lengde'])
			else:
				extras['STED_SEGMENT'] = "%s (%.2fm)" % (segment['kortform'], segment['lengde'])

		if debug or date_filter:
			extras['ID'] = segment_id
			extras['DATO_START'] = segment['metadata']['startdato'][:10]
			if "sluttdato" in segment['metadata']:
				extras['DATO_SLUTT'] = segment['metadata']['sluttdato'][:10]
			if "måledato" in segment:
				extras['DATO_MÅLT'] = segment['måledato'][:10]
			if "datafangstdato" in segment['geometri']:
				extras['DATO_DATAFANGST'] = segment['geometri']['datafangstdato'][:10]

		# Store new segment including super/parent relation

		if "superstedfesting" in segment:
			parent_id = segment['superstedfesting']['veglenkesekvensid']
			parent_start = segment['superstedfesting']['startposisjon']
			parent_end = segment['superstedfesting']['sluttposisjon']
		else:
			parent_id = segment['veglenkesekvensid']
			parent_start = segment['startposisjon']
			parent_end = segment['sluttposisjon']

		if parent_start >= parent_end:
			message ("  *** Super start > end position - %s\n" % segment_id)
			parent_start, parent_end = parent_end, parent_start
		if segment['startposisjon'] >= segment['sluttposisjon']:
			message ("  *** Sequence start > end position - %s\n" % segment_id)
			segment['startposisjon'], segment['sluttposisjon'] = segment['sluttposisjon'], segment['startposisjon']

		connection = ("KONNEKTERING" in segment['type'] or segment['typeVeg'] == "Rampe" and segment['type'] == "DETALJERT")

		sequence_id = segment['veglenkesekvensid']

		new_segment = {
			'id': segment_id,
			'rsref': ref_tuple,
			'parent': parent_id,
			'sequence': sequence_id,
			'parent_start': parent_start,
			'parent_end': parent_end,
			'sequence_start': segment['startposisjon'],
			'sequence_end': segment['sluttposisjon'],
			'start_node': segment['startnode'],
			'end_node': segment['sluttnode'],
			'length': segment['lengde'],
			'direction': meter_direction,  # For output only
			'reverse': reverse_geometry,
			'connection': connection,
			'highway': highway_type,
			'tags': tags,
			'extras': extras,
			'geometry': geometry,
			'geotype': "line"
		}

		segments[ segment_id ] = new_segment

		if sequence_id not in sequences:
			sequences[ sequence_id ] = [ segment_id ]
		else:
			sequences[ sequence_id ].append(segment_id)

		if parent_id not in parents:
			parents[ parent_id ] = [ segment_id ]
		else:
			parents[ parent_id ].append(segment_id)

		create_new_node (segment["startnode"], geometry[0], set([segment_id]))
		create_new_node (segment["sluttnode"], geometry[-1], set([segment_id]))



# Generate tagging for road object and store in network data strucutre

def process_road_object (road_object):

	tags = {}
	extras = {}
	object_id = str(road_object['metadata']['type']['id'])

	# Basic highway tagging

	properties = Properties({})
	if "egenskaper" in road_object:
		for attribute in road_object['egenskaper']:
			key = "VEGOBJEKT_%s_%s" % (object_id, attribute['navn'].replace(" ","_").replace(".","").replace(",","").upper())

			if "verdi" in attribute:
				properties[attribute['navn']] = attribute['verdi']
				value = attribute['verdi']
				if attribute['egenskapstype'] == "Stedfesting":
					value = "%f@%i %s" % (attribute['relativPosisjon'], attribute['veglenkesekvensid'], attribute['retning'])
					if "sideposisjon" in attribute:
						value += " " + attribute['sideposisjon']
				extras[key] = "%s" % value

			elif attribute['egenskapstype'] == "Stedfesting" and attribute['datatype'] == "GeomPunkt":
				properties[attribute['navn']] = attribute
				value = "%f@%i" % (attribute['relativPosisjon'], attribute['veglenkesekvensid'])
				if "retning" in attribute:
					value += " " + attribute['retning']
				if "sideposisjon" in attribute:
					value += " " + attribute['sideposisjon']
					extras['VEGOBJEKTSIDE'] = attribute['sideposisjon']
				extras[key] = value

	# Extra information for debugging

	if debug:
		if "egengeometri" in road_object['geometri']:
			extras['EGENGEOMETRI'] = "Ja"

		if "metadata" in road_object:
			extras['VEGOBJEKTTYPE'] = road_object['metadata']['type']['navn']
			extras['DATO_MODIFISERT'] = road_object['metadata']['sist_modifisert'][:10]
			extras['DATO_START'] = road_object['metadata']['startdato'][:10]

		if "måledato" in road_object:
			extras['DATO_MÅLT'] = road_object['måledato'][:10]

		if ("lokasjon" in road_object) and ("stedfestinger" in road_object['lokasjon']):
			i = 0
			for stedfesting in road_object['lokasjon']['stedfestinger']:
				i += 1
				place = ""
				if "kortform" in stedfesting:
					place = stedfesting['kortform']
				if "retning" in stedfesting:
					place = " " + stedfesting['retning']
				if "lengde" in stedfesting:
					place += " (%.2f)" % stedfesting['lengde']
				if place:
					extras["VEGLENKE_" + str(i)] = place

	i = 0
	for segment in road_object['vegsegmenter']:
		segment_tags = {}
		segment_extras = {}

		if "sluttdato" not in segment and "strekning" in segment['vegsystemreferanse']:
			geometry, geometry_type = process_geometry (segment['geometri']['wkt'])
			if len(geometry) > 1:
				message ("  *** More than one geometry - %i\n" % road_object['id'])
			geometry = geometry[0]
			highway_type = ""
			ref_tuple = None

			if geometry_type == "line":
				highway_type = tag_highway(segment, [], segment_tags, segment_extras)  # No lanes
				ref_tuple = get_hash(segment)
				segment_extras['STED_SEGMENT'] = "%f-%f@%i %s (%.2fm)" % (segment['startposisjon'], segment['sluttposisjon'], segment['veglenkesekvensid'], \
												segment['vegsystemreferanse']['strekning']['retning'], segment['lengde'])
			elif "relativPosisjon" in segment:
				segment_extras['STED_SEGMENT'] = "%f@%i %s" % (segment['relativPosisjon'], segment['veglenkesekvensid'], segment['vegsystemreferanse']['strekning']['retning'])
			elif "startposisjon" in segment and "sluttposisjon" in segment and segment['startposisjon'] == segment['sluttposisjon']:
				segment_extras['STED_SEGMENT'] = "%f@%i %s" % (segment['startposisjon'], segment['veglenkesekvensid'], segment['vegsystemreferanse']['strekning']['retning'])

			tag_object(object_id, properties, tags)

			i += 1
			segment_id = str(road_object['id'])
			segment_id += "-%i" % i
			segment_extras['ID'] = segment_id
			sequence_id = segment['veglenkesekvensid']

			new_segment = {
				'rsref': ref_tuple,
				'sequence': sequence_id,
				'tags': segment_tags,
				'extras': segment_extras,
				'reverse': False,
				'connection': False,
				'highway': highway_type,
				'geometry': geometry,
				'geotype': geometry_type
			} 

			update_tags(new_segment, tags, "")
			new_segment['extras'].update(extras)

#			if "metadata" in road_object:
#				new_segment['tags']['DATO_START'] = road_object['metadata']['startdato'][:10]

			segments[segment_id] = new_segment
			if geometry_type == "line":
				if sequence_id not in sequences:
					sequences[sequence_id] = [segment_id]
					parents[sequence_id] = [segment_id]
				else:
					sequences[sequence_id].append(segment_id)
					parents[sequence_id].append(segment_id)



# Indent XML output

def indent_tree(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_tree(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i



# Generate one osm tag for output

def tag_property (osm_element, tag_key, tag_value):

	tag_value = tag_value.strip()
	if tag_value:
		osm_element.append(ET.Element("tag", k=tag_key, v=tag_value))



# Output road network or objects to OSM file

def output_osm(output_filename):

	message ("\nSaving file... ")

	osm_id = -1000
	count = 0

	osm_root = ET.Element("osm", version="0.6", generator="nvdb2osm", upload="false")

	# First ouput all start/end nodes

	for node_id, node in iter(nodes.items()):
		osm_id -= 1
		osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node['point'][0]), lon=str(node['point'][1]))
		osm_root.append(osm_node)
		for key, value in iter(node['tags'].items()):
			tag_property (osm_node, key, value)
		if debug:
			for key, value in iter(node['extras'].items()):
				tag_property (osm_node, key, value)
		node['osmid'] = osm_id

	# Then output all ways and/or nodes

	for way_segments in ways:

		segment = segments[ way_segments[0] ]

		if segment['geotype'] == "line":  # Way
			osm_id -= 1
			osm_way_id = osm_id
			count += 1
			osm_way = ET.Element("way", id=str(osm_id), action="modify")
			osm_root.append(osm_way)

			for key, value in iter(segment['tags'].items()):
				tag_property (osm_way, key, value)
			if debug or object_tags or date_filter:
				for key, value in iter(segment['extras'].items()):
					if debug or object_tags and "VEGOBJEKT_" in key or date_filter:
						tag_property (osm_way, key, value)

		if "start_node" in segment:
			osm_way.append(ET.Element("nd", ref=str(nodes[segment['start_node']]['osmid'])))
	
		for segment_id in way_segments:
			segment = segments[segment_id]
					
			if segment['geotype'] == "line":  # Ways
				segment['osmid'] = osm_way_id

				if "start_node" in segment:
					line_geometry = segment['geometry'][1:-1]
				else:
					line_geometry = segment['geometry']

				for node in line_geometry:
					osm_id -= 1
					osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node[0]), lon=str(node[1]))
					osm_root.append(osm_node)
					for key, value in iter(node[2].items()):
						tag_property (osm_node, key, value)

					osm_way.append(ET.Element("nd", ref=str(osm_id)))

				if "end_node" in segment:
					osm_way.append(ET.Element("nd", ref=str(nodes[segment['end_node']]['osmid'])))

			else:  # Nodes
				for node in segment['geometry']:
					osm_id -= 1
					count += 1
					osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node[0]), lon=str(node[1]))
					osm_root.append(osm_node)

					for key, value in iter(node[2].items()):
						tag_property (osm_node, key, value)

					for key, value in iter(segment['tags'].items()):
						tag_property (osm_node, key, value)

					if debug or object_tags:
						for key, value in iter(segment['extras'].items()):
							if debug or object_tags and "VEGOBJEKT_" in key:
								tag_property (osm_node, key, value)

	# Output restriction relations

	for restriction_id, restriction in iter(turn_restrictions.items()):
		osm_id -= 1
		osm_relation = ET.Element("relation", id=str(osm_id))
		tag_property (osm_relation, "type", "restriction")
		tag_property (osm_relation, "restriction", restriction['type'])
		if restriction['fixme']:
			tag_property (osm_relation, "FIXME", "Please check turn restriction relation")
		if debug:
			tag_property (osm_relation, "ID", str(restriction_id))
		osm_root.append(osm_relation)

		osm_relation.append(ET.Element("member", type="way", ref=str(segments[ restriction['from_segment'] ]['osmid']), role="from"))
		osm_relation.append(ET.Element("member", type="way", ref=str(segments[ restriction['to_segment'] ]['osmid']), role="to"))
		osm_relation.append(ET.Element("member", type="node", ref=str(nodes[ restriction['via_node'] ]['osmid']), role="via"))

	# Produce OSM/XML file

	osm_tree = ET.ElementTree(osm_root)
	indent_tree(osm_root)
	osm_tree.write(output_filename, encoding="utf-8", method="xml", xml_declaration=True)

	message ("Saved %i elements in file '%s'\n\n" % (count, output_filename))



# Compute change in bearing at intersection between two segments
# Used to determine if way should be split at intersection

def compute_junction_angle (segment_id1, segment_id2):

	line1 = segments[segment_id1]['geometry']
	line2 = segments[segment_id2]['geometry']

	if segments[segment_id1]['end_node'] == segments[segment_id2]['start_node']:
		angle1 = compute_bearing(line1[-2], line1[-1])
		angle2 = compute_bearing(line2[0], line2[1])
	elif segments[segment_id1]['start_node'] == segments[segment_id2]['end_node']:
		angle1 = compute_bearing(line1[1], line1[0])
		angle2 = compute_bearing(line2[-1], line2[-2])
	elif segments[segment_id1]['start_node'] == segments[segment_id2]['start_node']:
		angle1 = compute_bearing(line1[1], line1[0])
		angle2 = compute_bearing(line2[0], line2[1])
	else:  # elif segments[segment_id1]['end_node'] == line2['end_node']:
		angle1 = compute_bearing(line1[-2], line1[-1])
		angle2 = compute_bearing(line2[-1], line2[-2])

	delta_angle = (angle2 - angle1 + 360) % 360

	if delta_angle > 180:
		delta_angle = delta_angle - 360

	return delta_angle



# Simplify line, i.e. reduce nodes within epsilon distance.
# Ramer-Douglas-Peucker method: https://en.wikipedia.org/wiki/Ramer–Douglas–Peucker_algorithm

def simplify_line(line, epsilon):

	dmax = 0.0
	index = 0
	for i in range(1, len(line) - 1):
		d = line_distance(line[0], line[-1], line[i])
		if d > dmax:
			index = i
			dmax = d

	if dmax >= epsilon:
		new_line = simplify_line(line[:index+1], epsilon)[:-1] + simplify_line(line[index:], epsilon)
	else:
		new_line = [line[0], line[-1]]

	return new_line



# Simplify all segments (remove redundant nodes).
# Apply to line geometry between tagged nodes.


def simplify_segments():

	message("Simplifying segments ... ")

	new_count = 0
	old_count = 0

	for segment_id, segment in iter(segments.items()):

		if segment['geotype'] == "line":
			remaining = segment['geometry'].copy()
			new_segment = [ remaining.pop(0) ]

			while remaining:
				subsegment = [ new_segment[-1] ]

				while remaining and not remaining[0][2]:  # Continue until tagged node
					subsegment.append(remaining.pop(0))

				if remaining:
					subsegment.append(remaining.pop(0))

				new_segment += simplify_line(subsegment, simplify_factor)[1:]

			new_count += len(new_segment)
			old_count += len(segment['geometry'])
			segment['geometry'] = new_segment

	if old_count > 0:
		removed = 100.0 * (old_count - new_count) / old_count
	else:
		removed = 0	
	message ("%i nodes removed (%i%%)\n" % (old_count - new_count, removed))



# Create common nodes at intersections between ssegments for road objects
# Currently brute force method only, and only works for intersections where both segments start/end

def optimize_object_network ():


	# Semi-automated alternative, merging nodes at start/end of segments
	# Remaining duplicates to be merged in JOSM

	if len(segments) < 10000:

		message ("Merging road object nodes ...\n")

		i = 0
		for segment_id, segment in iter(segments.items()):
			if segment['geotype'] == "line":

				i += 1
				start_node = segment['geometry'][0][0:2]
				end_node = segment['geometry'][-1][0:2]

				start_node_found = False
				end_node_found = False

				for node_id, node in iter(nodes.items()):
					if node['point'] == start_node:
						segment['start_node'] = node_id
						node['ways'].add(segment_id)
						start_node_found = True
						if end_node_found:
							break

					if node['point'] == end_node:
						segment['end_node'] = node_id
						node['ways'].add(segment_id)
						end_node_found = True
						if start_node_found:
							break

				if not start_node_found:
					segment['start_node'] = create_new_node("", start_node, set([segment_id]))

				if not end_node_found:
					if start_node == end_node:
						segment['end_node'] = segment['start_node']
					else:
						segment['end_node'] = create_new_node("", end_node, set([segment_id]))

				if i % 1000 == 0:
					message ("\r%i" % i)

		message ("\rDone merging\n")

	# Simple alternative, creating duplicate nodes, node merger to be done in JOSM

	else:
		for segment_id, segment in iter(segments.items()):
			if segment['geotype'] == "line":
				start_node = segment['geometry'][0][0:2]
				end_node = segment['geometry'][-1][0:2]
				segment['start_node'] = create_new_node ("", start_node, set([segment_id]))
				segment['end_node'] = create_new_node ("", end_node, set([segment_id]))



# Prepares road network and road objects for output
# 1) Consolidates tagging at intersection nodes
# 2) Simplifies network by combining consecutive segments into longer ways
# 3) Builds ways data strucutre for output

def optimize_network ():

	# For all connection segments, find attached segment and put connection segment into same sequence

	if longer_ways:

		for sequence_id, sequence_segment in iter(sequences.items()):
			for segment_id in sequence_segment[:]:
				segment = segments[ segment_id ]

				if segment['connection']:
					connected_id = None

					# Locate the connected segment, if any
					if len(nodes[ segment['start_node'] ]['ways']) == 2:
						connected_id = list(nodes[ segment['start_node'] ]['ways'] - set([segment_id]))[0]

					if connected_id:
						connected_segment = segments[ connected_id ]
						if segment['highway'] != connected_segment['highway'] or connected_segment['connection']:
							connected_id = None

					if not connected_id and len(nodes[ segment['end_node'] ]['ways']) == 2:
						connected_id = list(nodes[ segment['end_node'] ]['ways'] - set([segment_id]))[0]

					# Use tags from connected segment and relocate into same sequence. Sequence could become empty.
					if connected_id:
						connected_segment = segments[ connected_id ]
						if segment['highway'] == connected_segment['highway'] and not connected_segment['connection']:
							tags = copy.deepcopy(connected_segment['tags'])
							if "bridge" in tags and "bridge" not in segment['tags']:
								del tags['bridge']
							if "tunnel" in tags and "tunnel" not in segment['tags']:
								del tags['tunnel']
							if "layer" in tags and "layer" not in segment['tags']:
								del tags['layer']

							segment['tags'] = tags
							segment['reverse'] = connected_segment['reverse']
							if debug:
								segment['extras']['KONNEKTOR_KOPI'] = "Ja"

							if connected_segment['sequence'] != sequence_id:
								segment['sequence'] = connected_segment['sequence']
								sequences[ connected_segment['sequence'] ].append(segment_id)
								sequence_segment.remove(segment_id)
								if debug:
									segment['extras']['KONNEKTOR_SEKVENS'] = str(connected_segment['sequence'])


	# Copy node tags to node dict

	for segment_id, segment in iter(segments.items()):
		if segment['geotype'] == "line":
			nodes[segment['start_node']]['tags'].update(segment['geometry'][0][2])
			if segment['geotype'] == "line":
				nodes[segment['end_node']]['tags'].update(segment['geometry'][-1][2])

			if segment['reverse']:
				segment['start_node'], segment['end_node'] = segment['end_node'], segment['start_node']  # Swap for output
				segment['geometry'].reverse()

			if debug and "direction" in segment:
				segment['extras']['STED_INTERN'] = "%f-%f@%i %s (%.2fm)" \
					% (segment['parent_start'], segment['parent_end'], segment['parent'], segment['direction'], segment['length'])

	# Make longer combined ways for output

	if longer_ways:

		# Prepare list of segments group into road system references

		roadrefs = {}
		for segment_id, segment in iter(segments.items()):
			if segment['geotype'] == "line":
				if segment['rsref'] not in roadrefs:
					roadrefs[ segment['rsref'] ] = [ segment_id ]
				else:
					roadrefs[ segment['rsref'] ].append(segment_id)

		# Build connected ways within each road system reference

		for roadref, roadref_segments in iter(roadrefs.items()):  # Alternative grouping: iter(sequences.items())
			remaining_segments = copy.deepcopy(roadref_segments)

			while remaining_segments:

				segment = segments[remaining_segments[0]]
				way = [ remaining_segments[0] ]
				remaining_segments.pop(0)
				first_node = segment['start_node']
				last_node = segment['end_node']

				# Build way forward

				found = True
				while found:
					found = False
					for segment_id in remaining_segments[:]:
						segment = segments[segment_id]
						if segment['start_node'] == last_node and not nodes[last_node]['break']:
							angle = compute_junction_angle(way[-1], segment_id)
							if (abs(angle) < angle_margin / 2.0 or segment['connection'] or segments[ way[-1] ]['connection']):
								last_node = segment['end_node']
								way.append(segment_id)
								remaining_segments.remove(segment_id)
								found = True
								break
							else:
								nodes[segments[segment_id]['start_node']]['extras']['VINKEL'] = str(int(angle))

				# Build way backward

				found = True
				while found:
					found = False
					for segment_id in remaining_segments[:]:
						segment = segments[segment_id]
						if segment['end_node'] == first_node and not nodes[first_node]['break']:
							angle = compute_junction_angle(segment_id, way[0])
							if abs(angle) < angle_margin / 2.0 or segment['connection'] or segments[ way[0] ]['connection']:
								first_node = segment['start_node']
								way.insert(0, segment_id)
								remaining_segments.remove(segment_id)
								found = True
								break
							else:
								nodes[segments[segment_id]['end_node']]['extras']['VINKEL'] = str(int(angle))

				# Create new ways, each with identical segment tags
				# Always include connection segments but exclude their tags

				new_way = []
				way_tags = {}
#				for segment_id in way:
#					if not segments[segment_id]['connection']:
#						way_tags = segments[segment_id]['tags']
#						break
				if not way_tags:
					way_tags = segments[ way[0] ]['tags']

				for segment_id in way:
					if segments[segment_id]['tags'] == way_tags:
						new_way.append(segment_id)
#					elif segments[segment_id]['connection']:
#						new_way.append(segment_id)
#						segments[segment_id]['tags'] = way_tags
					else:
						ways.append(new_way)
						new_way = [ segment_id ]
						way_tags = segments[ segment_id ]['tags']

				ways.append(new_way)

	else:
		for segment_id, segment in iter(segments.items()):
			if segment['geotype'] == "line":
				ways.append([segment_id])

	# Add remaining points

	for segment_id, segment in iter(segments.items()):
		if segment['geotype'] == "point":
			ways.append([segment_id])



# Fix errors in api
# Remove duplicate segments from road network

def fix_network():

	message ("Removing duplicate segments... ")

	count_removed = 0

	for segment_id in list(segments.keys()):
		segment = segments[ segment_id ]

		if segment['length'] <= node_margin:
			for node_id in [segment['start_node'], segment['end_node']]:
				if len(nodes[ node_id ]['ways']) == 2:
					next_segment_id = list(nodes[ node_id ]['ways'] - set([segment_id]))[0]
					next_segment = segments[ next_segment_id ]

					if next_segment['sequence'] == segment['sequence'] and next_segment['parent'] == segment['parent']:

						if node_id == segment['end_node']:
							next_segment['geometry'][0] = copy.deepcopy(segment['geometry'][0])
							next_segment['start_node'] = segment['start_node']
							next_segment['parent_start'] = segment['parent_start']
							next_segment['sequence_start'] = segment['sequence_start']
							next_segment['length'] += segment['length']
							nodes[ segment['start_node'] ]['ways'].remove(segment_id)
							nodes[ segment['start_node'] ]['ways'].add(next_segment_id)
						else:
							next_segment['geometry'][-1] = copy.deepcopy(segment['geometry'][-1])
							next_segment['end_node'] = segment['end_node']
							next_segment['parent_end'] = segment['parent_end']
							next_segment['sequence_end'] = segment['sequence_end']
							next_segment['length'] += segment['length']
							nodes[ segment['end_node'] ]['ways'].remove(segment_id)
							nodes[ segment['end_node'] ]['ways'].add(next_segment_id)

						sequences[ segment['sequence'] ].remove(segment_id)
						parents[ segment['parent'] ].remove(segment_id)
						del segments[ segment_id ]
						del nodes[ node_id ]
						count_removed += 1
						break

	message ("Removed %i segments\n" % count_removed)



# Fetch road network or road objects from NVDB, including paging.
# Saves input data to file for debugging, if chosen.

def get_data(url, output_filename):

	global api_calls

	message ("Loading NVDB data...\n")

	# Load segment IDs from last month

	if date_filter:
		if date_filter[5:7] == "01":
			last_filter = "%i-12" % (int(date_filter[:4]) - 1)
		else:
			last_filter = "%s-%02i" % (date_filter[:4], int(date_filter[5:7]) - 1)

		history_filename = "nvdb_00_Norge_%s_history.json" % last_filter
		file_path = os.path.expanduser(import_folder + history_filename)
		if not os.path.isfile(file_path):
			sys.exit("*** Log file '%s' for last month not found\n\n")
			
		file = open(file_path)
		last_history = set()
		for ref in json.load(file):
			last_history.add(ref.rpartition("-")[0])
		file.close()
		new_history = []

	if save_input:
		debug_file = open("nvdb_%s_input.json" % function, "w")
		debug_file.write("[\n")

	returned = 1
	total_returned = 0

	# Loop until no more pages to fetch

	while returned > 0:

#		if api_calls % 50 == 0:
#			time.sleep(1)

#		request = urllib.request.Request(url, headers=request_headers)
#		file = open_url(request)  # urllib.request.urlopen(request)
#		data = json.load(file)
#		file.close()

		data = load_data(url)
		api_calls += 1

		if save_input:
			debug_file.write(json.dumps(data, indent=2, ensure_ascii=False))

		for record in data['objekter']:
			if "geometri" in record:
				if date_filter:
					new_history.append(record['referanse'])
				if "vegobjekt" in url:
					process_road_object(record)
				elif "vegnett" in url and (not date_filter or record['referanse'].rpartition("-")[0] not in last_history):
#						record['metadata']['startdato'][:len(date_filter)] == date_filter and \
#						record['geometri']['datafangstdato'] > str(int(record['metadata']['startdato'][:4]) - years_back) + record['metadata']['startdato'][4:] and \
#						record['referanse'] not in last_history):
					process_road_network(record)

		returned = data['metadata']['returnert']
		url = data['metadata']['neste']['href']
		total_returned += returned
		message ("\r%i" % total_returned)

		if save_input and returned > 0:
			debug_file.write(",\n")

	# Save all segment IDs to make diff next month

	if date_filter:
		history_filename = "nvdb_00_Norge_%s_history.json" % date_filter
		file = open(history_filename, "w")
		json.dump(new_history, file, indent=1)
		file.close()		
		message("\rSaved log of road network to '%s'\n" % history_filename)			

	if save_input:
		debug_file.write("]\n")
		debug_file.close()

	message("\rDone processing %i road objects/segments\n" % total_returned)



# Identify municipality name, unless more than one hit
# Returns municipality number, or input paramter if not found

def get_municipality (parameter):

	if parameter.isdigit():
		return parameter

	else:
		parameter = parameter
		found_id = ""
		duplicate = False
		for mun_id, mun_name in iter(municipalities.items()):
			if parameter.lower() == mun_name.lower():
				return mun_id
			elif parameter.lower() in mun_name.lower():
				if found_id:
					duplicate = True
				else:
					found_id = mun_id

		if found_id and not duplicate:
			return found_id
		else:
			return parameter



# Main function to generate file for one municipality, or other query.

def main_run(url, municipality):

	global api_calls

	start_time = time.time()
	api_calls = 0

	# Set output filename

	output_filename = "nvdb"

	if municipality:
		message ("Municipality:   #%s %s\n" % (municipality, municipalities[municipality]))
		if municipality == "00":
			url += "&fylke=" + ",".join(counties) # All counties
		elif len(municipality) == 2:
			url += "&fylke=" + municipality
		else:
			url += "&kommune=" + municipality

		if not object_type:
			output_filename += "_" + municipality + "_" + municipalities[municipality].replace(" ", "_")

	if object_type:
		message ("Road object:    #%s %s\n" % (object_type, object_types[object_type]))
		output_filename += "_" + object_type + "_" + object_types[object_type].replace(" ", "_").replace(",", "").replace("/","_")

	if output_filename == "nvdb":
		output_filename += "_" + function

	if date_filter:
		output_filename += "_" + date_filter

	if include_objects and function == "vegnett" or longer_ways:
		output_filename = output_filename + ".osm"
	else:
		output_filename = output_filename + "_segmentert.osm"

	for argument in sys.argv[3:]:
		if ".osm" in argument.lower():
			output_filename = argument.replace(" ", "_")

	if debug:
		message("Query:          %s\n" % url)
	message("Output filename: %s\n\n" % output_filename)

	# Init

	nodes.clear()      # All endpoint nodes
	segments.clear()   # All segments and road objects
	sequences.clear()  # List of segments in each sequence
	parents.clear()    # List of segments for each super sequence + normal sequences
	ways.clear()       # Ways for output

	tunnels.clear()	# Tunnels
	turn_restrictions.clear()

	master_node_id = 0     # Id for additional endpoint nodes
	master_segment_id = 0  # Id for additional segments

	get_data(url, output_filename)

	if function == "vegnett":
		fix_network()

	# Read objects

	if function == "vegnett" and include_objects:

		# Points
		get_road_object ("103")  # Speed bumps
		get_road_object ("174")  # Pedestrian crossing (sometimes incorrect segment i NVDB)
		get_road_object ("100")  # Railway crossing
		get_road_object ("89")   # Traffic signal
		get_road_object ("22")   # Cattle grid
		get_road_object ("607")  # Barrier, motor access blocked
#		get_road_object ("23")   # Barrier
		get_road_object ("47")   # Passing place
		get_road_object ("64")   # Ferry terminal
		get_road_object ("37")   # Junction
		
		# Ways
		get_road_object ("581")  # Tunnel node - 1st pass
		get_road_object ("67")   # Tunnel ways - 2nd pass
		get_road_object ("66")   # Avalanche protector		
		get_road_object ("60")   # Bridges
		get_road_object ("595")  # Motorway, motorroad
		get_road_object ("538")  # Address names  (now also included in basic road network segments)
		get_road_object ("770")  # Ferry route names
		get_road_object ("105")  # Maxspeeds
		get_road_object ("241")  # Surface
		get_road_object ("821")  # Functional road class
		get_road_object ("856")  # Access restrictions
		get_road_object ("107")  # Weather restrictions
		get_road_object ("591")  # Maxheight
		get_road_object ("904")  # Maxweight, maxlength
		get_road_object ("922")  # Highway class undetermined
		get_road_object ("923")  # Diversion
		get_road_object ("924")  # Service road
#		get_road_object ("777")  # Scenic routes
		
		get_road_object ("96", property="(5530=7643)")  # Stop sign
#		get_road_object ("96", property="(5530=7655)")  # No bicycle
#		get_road_object ("96", property="(5530=7656)")  # No pedestrian
#		get_road_object ("96", property="(5530=7657)")  # No bicycle nor pedestrian
		
		get_road_object ("573")  # Turn restrictions

	elif function == "vegnett" and len(municipality) == 2:
		get_road_object ("595")  # Motorway, motorroad
		get_road_object ("105")  # Maxspeeds
		get_road_object ("581")  # Tunnel node - 1st pass
		get_road_object ("67")   # Tunnel ways - 2nd pass
		get_road_object ("60")   # Bridges
		get_road_object ("856")  # Access restrictions
	
	if function == "vegobjekt":
		optimize_object_network()

	if not debug:  # and (function == "vegnett" or len(segments) < 10000):
		simplify_segments()

	optimize_network()

	output_osm(output_filename)

	duration = time.time() - start_time
	message ("Time: %i seconds (%i segments per second)\n" % (duration, len(segments) / duration))
	message ("API calls: %i (%.1f per second)\n\n" % (api_calls, api_calls / duration))



# Main program

if __name__ == '__main__':

	message ("\nnvdb2osm v%s\n\n" % version)

	# Get database status

	data_status = load_data(server + "status")
	api_status = load_data(server + "status/versjoner")
	message ("Server:         %s\n" % server)
	message ("API:            v%s, %s\n" % (api_status['nvdbapi-v3'][-1]['version'], api_status['nvdbapi-v3'][-1]['installDate']))
	message ("Data catalogue: v%s, %s\n" % (data_status['datagrunnlag']['datakatalog']['versjon'], data_status['datagrunnlag']['datakatalog']['dato']))
	message ("Last DB update: %s\n\n" % data_status['datagrunnlag']['sist_oppdatert'][:10])

	# Get municipalities and road object types

	data = load_data("https://ws.geonorge.no/kommuneinfo/v1/fylkerkommuner?filtrer=fylkesnummer%2Cfylkesnavn%2Ckommuner.kommunenummer%2Ckommuner.kommunenavnNorsk")
	municipalities = { '00': 'Norge' }
	counties = []
	for county in data:
		if county['fylkesnavn'] == "Oslo":
			county['fylkesnavn'] = "Oslo fylke"
		municipalities[ county['fylkesnummer'] ] = county['fylkesnavn']
		counties.append(county['fylkesnummer'])
		for municipality in county['kommuner']:
			municipalities[ municipality['kommunenummer'] ] = municipality['kommunenavnNorsk']

	data = load_data(server + "vegobjekttyper")
	object_types = {}
	for entry in data:
		object_types[ str(entry['id']) ] = entry['navn']
	del data

	# Get street name corrections from GitHub

	name_corrections = load_data("https://raw.githubusercontent.com/NKAmapper/addr2osm/master/corrections.json")
	name_ending_corrections = set(load_data("https://raw.githubusercontent.com/NKAmapper/addr2osm/master/corrections_ending.json"))

	# Build query

	url = ""
	municipality = ""
	url_bbox = ""
	start_municipality = ""
	object_type = ""

	if len(sys.argv) > 2:
		if sys.argv[1] == "-vegnett" and len(sys.argv) >= 3:
			municipality = get_municipality(sys.argv[2])
			url = server + "vegnett/veglenkesekvenser/segmentert?srid=wgs84" # &kommune=" + municipality
			if municipality == "00" and len(sys.argv) > 3 and sys.argv[3].isdigit():
				start_municipality = sys.argv[3]

		elif sys.argv[1] == "-vegref" and len(sys.argv) >= 3:
			url = server + "vegnett/veglenkesekvenser/segmentert?srid=wgs84&vegsystemreferanse=" + sys.argv[2]
			include_objects = False

		elif sys.argv[1] == "-vegobjekt" and len(sys.argv) >= 3 and sys.argv[2].isdigit():
			object_type = sys.argv[2]
			url = server + "vegobjekter/" + sys.argv[2] + "?inkluder=metadata,egenskaper,geometri,lokasjon,vegsegmenter&alle_versjoner=false&srid=wgs84"
			if len(sys.argv) >= 4 and sys.argv[3][0] != "-":
				municipality = get_municipality(sys.argv[3])

		elif sys.argv[1] == "-vegurl" and "atlas.vegvesen.no" in sys.argv[2] and "?" in sys.argv[2]:
			url = sys.argv[2]
			if "srid=vgs84" not in url and "srid=4326" not in url:
				url += "&srid=wgs84"
			if "kartutsnitt" in url:
				url_split = url.split("?")[1].split("&")
				for paramter in url_split:
					if "kartutsnitt" in paramter:
						url_bbox = paramter
						break
			message ("Vegkart.no URL: %s\n\n" % url)

		if "-segmentert" in sys.argv or "-segment" in sys.argv:
			longer_ways = False
			include_objects = False

		if "-debug" in sys.argv:
			debug = True
			save_input = False

		if "-dato" in sys.argv:
			date_filter = sys.argv[ sys.argv.index("-dato") + 1 ]
			if len(municipality) == 2:
				include_objects = False
#				longer_ways = False

		if "vegnett" in url:
			function = "vegnett"
		elif "vegobjekt" in url:
			function = "vegobjekt"
			object_tags = True
		else:
			function = ""

	# Check parameters

	if url and municipality and municipality not in municipalities:
		message ("*** Municipality %s not found\n" % municipality)
		url = ""

	if url and object_type and object_type not in object_types:
		message ("*** Road object type %s not found\n" % object_type)
		url = ""

	if not url:
		message("\nPlease provide main parameters in one of the following ways:\n")
		message('  nvdb2osm -vegnett <municipality>  -->  Road network for municipality number (4 digits) or name, or "Norge" for all municipalities\n')
		message('  nvdb2osm -vegref <reference>  -->  Road network for road reference code (e.g. "0400Ea6")\n')		
		message('  nvdb2osm -vegobjekt <object>  -->  Road object number (2-3 digits) for entire country\n')
		message('  nvdb2osm -vegobjekt <object> [municipality]  -->  Road object number (2-3 digits) for municipality number (4 digits) or name\n')
		message('  nvdb2osm -vegurl "<api url string>"  -->  Any api generated from vegkart.no (but only WGS84/4326 bounding box supported)\n\n')
		sys.exit()

	# Init

	nodes = {}      # All endpoint nodes
	segments = {}   # All segments and road objects
	sequences = {}  # List of segments in each sequence
	parents = {}    # List of segments for each super sequence + normal sequences
	ways = []       # Ways for output

	tunnels = {}	# Tunnels
	turn_restrictions = {}

	master_node_id = 0     # Id for additional endpoint nodes
	master_segment_id = 0  # Id for additional segments

	# Run program
	# municipality_id is identifying entity to generate

	if function == "vegnett" and len(municipality) == 2 and not date_filter:
		for municipality_id in sorted(list(municipalities.keys())):
			if len(municipality_id) == 4 and (municipality == "00" or municipality_id[:2] == municipality) and municipality_id >= start_municipality:
				main_run(url, municipality_id)
				message("\n")

	else:
		municipality_id = municipality
		main_run(url, municipality)

	message ("\nDone\n\n")

