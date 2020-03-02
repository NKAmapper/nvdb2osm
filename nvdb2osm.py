#!/usr/bin/env python
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
import urllib2
import sys
import copy
import math
import calendar
import time
from xml.etree import ElementTree as ET


version = "0.4.3"

longer_ways = True      # True: Concatenate segments with identical tags into longer ways, within sequence
debug = False           # True: Include detailed information tags for debugging
include_objects = True  # True: Include road objects in network output
object_tags = False     # True: Include detailed road object information tags

segment_margin = 10.0   # Tolerance for snap of way property to way start/end (meters)
point_margin = 2.0      # Tolerance for snap of point to way start/end (meters)
node_margin = 1.0       # Tolerance for snap of point to nodes of way (meters)
simplify_margin = 0.5   # Minimum distance between way nodes (meters)
angle_margin = 45.0     # Maximum change of bearing at intersection for merging segments into longer ways (degrees)
max_travel_depth = 10   # Maximum depth of recursive calls when finding route


#server = "https://nvdbapiles-v3.utv.atlas.vegvesen.no/"  # UTV - Utvikling
#server = "https://nvdbapiles-v3-stm.utv.atlas.vegvesen.no/"  # STM - Systemtest
#server = "https://nvdbapiles-v3.test.atlas.vegvesen.no/"  # ATM - Test, akseptansetest
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
	'T': u'På terrenget/på bakkenivå',
	'B': 'I bygning/bygningsmessig anlegg',
	'L': 'I luft',
	'U': 'Under terrenget',
	'S': u'På sjøbunnen',
	'O': u'På vannoverflaten',
	'V': 'Alltid i vann',
	'D': 'Tidvis under vann',
	'I': u'På isbre',
	'W': u'Under sjøbunnen',
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
			tags['motor_vehicle' + suffix] = psv[direction].replace("designated","no")

		elif psv[direction]:
			tags['psv' + suffix] = psv[direction]
			if psv['forward'] == psv['backward']:
				suffix = ""
			tags['motor_vehicle' + suffix] = psv[direction].replace("designated","no")

	# Lanes tagging if mroe than one line in either direction

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

	ref = segment['vegsystemreferanse']['vegsystem']

	# Set key according to status (proposed, construction, existing)

	if ref['fase'] == "A":
		tags['highway'] = "construction"
		tag_key = "construction"
	elif ref['fase'] ==  "P":
		if segment['typeVeg'] in ["Bilferje", "Passasjerferje"]:
			tag_key = "proposed:route"
		else:
			tag_key = "proposed:highway"
	else:
		if segment['typeVeg'] in ["Bilferje", "Passasjerferje"]:
			tag_key = "route"
		else:
			tag_key = "highway"

	# Special case: Strange data tagged as crossing

	if segment['typeVeg'] in ["Kanalisert veg", "Enkel bilveg"] and \
			"strekning" in segment['vegsystemreferanse'] and segment['vegsystemreferanse']['strekning']['trafikantgruppe'] == "G" or \
			segment['typeVeg'] == "Gang- og sykkelveg" and u"topologinivå" in segment and segment[u'topologinivå'] == "KJOREBANE":
		tags[tag_key] = "footway"
		tags['footway'] = "crossing"
		tags['bicycle'] = "yes"
		segment['typeVeg'] == "Gangfelt"

	# Tagging for normal highways (cars)

	elif segment['typeVeg'] in ["Enkel bilveg", "Kanalisert veg", "Rampe", u"Rundkjøring"]:  # Regular highways (excluding "kjørefelt")

		if "sideanlegg" in segment['vegsystemreferanse'] or \
				len(lanes) == 1 and "K" in lanes[0] and ref['vegkategori'] in ["E", "R", "F"] and segment[u'detaljnivå'] != u"Kjørebane" and \
				(segment['typeVeg'] != "Enkel bilveg" or "kryssystem" in segment['vegsystemreferanse']): # Trafikklommer/rasteplasser
			tags[tag_key] = "unclassified"

		else:
			if (ref['vegkategori'] == "F") and (ref['nummer'] < 1000):  # After reform
				tags[tag_key] = "primary"
			else:
				tags[tag_key] = road_category[ ref['vegkategori'] ]['tag']

			if ref['vegkategori'] in ["E", "R", "F"]:
				if segment['typeVeg'] == "Rampe" or segment[u'detaljnivå'] == u"Kjørefelt" and lanes and "H" in lanes[0]:
					tags[tag_key] += "_link"
				tags['ref'] = get_ref(ref['vegkategori'], ref['nummer'])

		if segment['typeVeg'] == u"Rundkjøring":
			tags['junction'] = "roundabout"

		if lanes:
			tags.update (process_lanes (lanes))
		elif segment[u'detaljnivå'] != "Vegtrase" and segment['typeVeg'] in ["Kanalisert veg", "Rampe", u"Rundkjøring"]:
			tags['oneway'] = "yes"

		if segment[u'detaljnivå'] == u"Kjørefelt" and not (lanes and ("K" in lanes[0] and lanes[0] != "SVKL")): # or "H" in lanes[0])):
#			tags.clear()
#			tags['FIXME'] = 'Please replace way with "turn:lanes" on main way'
			if tag_key in tags:
				del tags[tag_key]
			if "turn:lanes" in tags:
				del tags['turn:lanes']
#			if lanes and  "V1" in lanes[0] and "turn:lanes" not in tags:
#				tags['turn:lanes'] = "left"

	# All other highway types

	elif segment['typeVeg'] == u"Gågate":  # Pedestrian street
		tags[tag_key] = "pedestrian"
		tags['bicycle'] = "yes"

	elif segment['typeVeg'] == "Gatetun":  # Living street
		tags[tag_key] = "living_street"

	elif segment['typeVeg'] == "Gang- og sykkelveg":  # Combined cycleway/footway		
		if ref['vegkategori'] != "P":
			tags[tag_key] = "cycleway"
			tags['foot'] = "designated"
			tags['segregated'] = "no"
		else:
			tags[tag_key] = "footway"
			tags['bicycle'] = "yes"

	elif segment['typeVeg'] == "Sykkelveg":  # Express cycleway
		tags[tag_key] = "cycleway"
		tags["foot"] = "designated"
		tags['segregated'] = "yes"
		if len(lanes) == 2 and lanes[0] == "1S" and lanes[1] == "2S":
			tags['lanes'] = "2"

	elif segment['typeVeg'] in ["Bilferje", "Passasjerferje"]:  # Ferry
		tags[tag_key] = "ferry"
		tags['ref'] = get_ref(ref['vegkategori'], ref['nummer'])

	elif segment['typeVeg'] == "Gangveg":  # Footway
		tags[tag_key] = "footway"
		tags['bicycle'] = "yes"

	elif segment['typeVeg'] == "Fortau":  # Sidewalk
		tags[tag_key] = "footway"
		tags['bicycle'] = "yes"
		tags['footway'] = "sidewalk"

	elif segment['typeVeg'] == "Gangfelt":  # Crossing
		tags[tag_key] = "footway"
		tags['bicycle'] = "yes"
		tags['footway'] = "crossing"

	elif segment['typeVeg'] == "Trapp":  # Stairs
		tags[tag_key] = "steps"

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

	# Information tags for debugging

	if debug:
		extras[u"DETALJNIVÅ"] = segment[u'detaljnivå']
		extras["TYPEVEG"] = segment['typeVeg']			

		if lanes:
			extras['FELT'] = " ".join(lanes)

		if medium:
			extras["MEDIUM"] = "#" + medium + " " + medium_types[ medium ]

		if u"topologinivå" in segment:
			extras[u"TOPOLOGINIVÅ"] = segment[u'topologinivå']

		ref = segment['vegsystemreferanse']
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



# Produce tagging for supported road objects

def tag_object (object_id, properties, tags):

	if object_id == "595":
		if properties['Motorvegtype'] == "Motorveg":
			tags['motorway'] = "yes"  # Dummy to flag new highway class
		elif properties['Motorvegtype'] == "Motortrafikkveg":
			tags['motorroad'] = "yes"

	elif object_id == "821":
		if properties['Vegklasse'] < 6:  # Only class 4 and 5 ?
			tags['highway'] = "tertiary"  # Dummy to flag new highway class below secondary level

	elif object_id == "105":
		if "Fartsgrense" in properties: 
			tags['maxspeed'] = str(properties["Fartsgrense"])

	elif object_id == "538":
		if "Gatenavn" in properties:
			tags['name'] = properties['Gatenavn'].replace("  "," ").strip()

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

	elif object_id == "60":
		tags['bridge'] = "yes"
		tags['layer'] = "1"		
		if "Navn" in properties:
			tags['bridge:description'] = properties['Navn'].replace("  "," ").strip()
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

	elif object_id == "856":
		restrictions = {
			u'Forbudt for gående og syklende': {'foot': 'no', 'bicycle': 'no'},
			'Forbudt for motortrafikk': {'motor_vehicle': 'no'},
			'Motortrafikk kun tillatt for varetransport': {'motor_vehicle': 'delivery'},
			u'Forbudt for gående': {'foot': 'no'},
			u'Motortrafikk kun tillatt for kjøring til eiendommer': {'motor_vehicle': 'destination'},
			'Forbudt for lastebil og trekkbil': {'hgv': 'no'},
			u'Motortrafikk kun tillatt for varetransport og kjøring til eiendommer': {'motor_vehicle': 'destination'},
			'Forbudt for lastebil og trekkbil m unntak': {'hgv': 'permissive'},
			'Forbudt for motorsykkel': {'motorcycle': 'no'},
			u'Gjennomkjøring forbudt': {'motor_vehicle': 'destination'},
			'Forbudt for motorsykkel og moped': {'motorcycle': 'no', 'moped': 'no'},
			'Forbudt for motortrafikk unntatt buss': {'motor_vehicle': 'no', 'bus': 'yes'},
			'Forbudt for motortrafikk unntatt buss og taxi': {'motor_vehicle': 'no', 'psv': 'yes'},
			'Forbudt for motortrafikk unntatt moped': {'motor_vehicle': 'no', 'moped': 'yes'},
			'Forbudt for motortrafikk unntatt spesiell motorvogntype': {'motor_vehicle': 'permissive'},
			'Forbudt for motortrafikk unntatt taxi': {'motor_vehicle': 'no', 'taxi': 'yes'},
			'Forbudt for motortrafikk unntatt varetransport': {'motor_vehicle': 'delivery'},
			'Forbudt for traktor': {'agriculatural': 'no'},
			u'Gjennomkjøring forbudt for lastebil og trekkbil': {'hgv': 'destination'},
			u'Sykling mot kjøreretningen tillatt': {'oneway:bicycle': 'no'},
			u'Gjennomkjøring forbudt til veg eller gate': {'motor_vehicle': 'destination'},
			u'Motortrafikk kun tillatt for kjøring til virksomhet eller adresse': {'motor_vehicle': 'destination'},
			u'Forbudt for alle kjøretøy': {'motor_vehicle': 'no'},
			'Forbudt for syklende': {'bicycle': 'no'}
		}
		if "Trafikkreguleringer" in properties:
			if properties['Trafikkreguleringer'].strip() in restrictions:
				tags.update(restrictions[ properties['Trafikkreguleringer'].strip() ])
			else:
				message ("  *** Unknown access restriction: %s\n" % properties['Trafikkreguleringer'])

	elif object_id == "103":
		if properties['Type'] == "Fartshump":
			tags['traffic_calming'] = "table"  # Mostly long/wide humps

	elif object_id == "22":
		tags['barrier'] = "cattle_grid"			

	elif object_id == "47":
		if properties[u'Bruksområde'] == u"Møteplass":
			tags['highway'] = "passing_place"

	elif object_id == "607":  # Vegsperring
		barriers = {
			'Betongkjegle': 'bollard',
			u'Rørgelender': 'cycle_barrier',
			'Steinblokk': 'block',
			'New Jersey': 'jersey_barrier',
			'Bussluse': 'bus_trap',
			u'Låst bom': 'lift_gate',
			'Trafikkavviser': 'bollard',
			'Bilsperre': 'gate',
			u'Bom med automatisk åpner': 'lift_gate'
		}
		if properties['Type'] in barriers:
			tags['barrier'] = barriers[ properties['Type'] ]
		else:
			if "Type" in properties:
				message ("  *** Unknown barrier type: %s\n" % properties['Type'])
			tags['barrier'] = "yes"

	elif object_id == "174":
		tags['highway'] = "crossing"		
		if properties['Trafikklys'] == "Ja":
			tags['crossing'] = "controlled"  # crossing = controlled / traffic_signals ?
		elif properties['Markering av striper'] == "Malte striper":
			tags['crossing'] = "marked"
		elif properties['Markering av striper'] == "Ikke striper":
			tags['crossing'] = "unmarked"
		if properties [u"Trafikkøy"] == "Ja":
			tags['crossing:island'] = "yes"

	elif object_id == "100":
		if "I plan" in properties['Type']:
			tags['railway'] = "level_crossing"
			if "bom" in properties['Type'] or "grind" in properties['Type']:
				tags['crossing:barrier'] = "yes"
			if "lys" in properties['Type']:
				tags['crossing:light'] = "yes"  # crossing = traffic_light ?
			if "uten sikring" in properties['Type']:
				tags['crossing'] = "uncontrolled"

	elif object_id == "89":  # Traffic signal
		if properties[u'Bruksområde'] in ["Vegkryss", "Skyttelsignalanlegg"]:
			tags['highway'] = "traffic_signals"
		elif properties[u'Bruksområde'] == "Gangfelt":
			tags['highway'] = "crossing"
			tags['crossing'] = "traffic_signals"
		elif "Navn" in properties:
			tags['highway'] = "traffic_signals"			

	elif object_id == "241":
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
			elif properties['Massetype'] == u"Stålgitter (bru)":
				tags['surface'] = "metal"

	elif object_id == "591":
		if u"Skilta høyde" in properties:
			tags['maxheight'] = str(properties[u'Skilta høyde'])

	elif object_id == "904":
		if "tonn" in properties['Bruksklasse'] and "50 tonn" not in properties['Bruksklasse']:
			tags['maxweight'] = properties['Bruksklasse'][-7:-5]
		if properties['Maks vogntoglengde'] in ['12,40', '15,00']:
			tags['maxlength'] = properties['Maks vogntoglengde'].replace(",", ".")

	elif object_id == "64":
		tags['amenity'] = "ferry_terminal"
		if "Navn" in properties:
			tags['name'] = properties['Navn'].replace("Fk","").replace("Kai","").replace("  "," ").strip()

	elif object_id == "37":
		if "Planskilt kryss" in properties['Type']:
			tags['highway'] = "motorway_junction"
			if "Kryssnummer" in properties:
				tags['ref'] = str(properties['Kryssnummer'])
			if "Navn" in properties:
				tags['name'] = properties['Navn'].replace("  ", " ").strip()

	elif object_id == "96":
		if "Trafikk" in properties['Ansiktsside, rettet mot']:
			if properties['Skiltnummer'] == "204 - Stopp":  # 7643
				tags['highway'] = "stop"
			elif properties['Skiltnummer'] == "202 - Vikeplikt":  # 7642
				tags['highway'] = "give_way"

	elif object_id == "107":
		if "Vinterstengt, fra dato" in properties or "Vinterstengt, til dato" in properties:
			tags['snowplowing'] = "no"
			if "Vinterstengt, fra dato" in properties and "Vinterstengt, til dato" in properties:
				tags['motor_vehicle:conditional'] = "no @ %s-%s" % (calendar.month_abbr[int(properties['Vinterstengt, fra dato'][0:2])], \
																	calendar.month_abbr[int(properties['Vinterstengt, til dato'][0:2])])
			if "Tilleggsinformasjon" in properties:
				tags['description'] = properties['Tilleggsinformasjon'].replace("  "," ")

	elif object_id == "291":
		tags['hazard'] = "animal_crossing"
		if properties['Art'] == "Hjort":
			tags['species:en'] = "deer"
		elif properties['Art'] == "Elg":
			tags['species:en'] = "moose"
		elif properties['Art'] == "Rein":
			tags['species:en'] = "raindeer"
		elif properties['Art'] == "Rådyr":
			tags['species:en'] = "venison"

	elif object_id == "449":
		tags['highway'] = "footway"
		tags['tunnel'] = "yes"
		tags['layer'] = "-1"
		tags['emergency'] = "designated"



# Update tags in segment, including required corrections for motorway, maxspeed and street name
# This is the only place to make road object tagging dependent on earlier basic highway tagging based on road reference

def update_tags (segment, tags):

	# Change highway type to motorway if given
	if "motorway" in tags:
		if "highway" in segment['tags']:
			if "link" in segment['tags']['highway']:
				segment['tags']['highway'] = "motorway_link"
			else:
				segment['tags']['highway'] = "motorway"
		segment['tags'].update(tags)
		del segment['tags']['motorway']

	# No maxspeed for service
	elif "maxspeed" in tags:
		if not ("highway" in segment['tags'] and segment['tags']['highway'] == "service"):
			segment['tags'].update(tags)

	# No street name for cycleways/footways and roundabouts
	elif "name" in tags:
		if not ("junction" in segment['tags'] and segment['tags']['junction'] == "roundabout"):
			segment['tags'].update(tags)

	# Apply tertiary tag to service and residential roads only
	elif "highway" in tags and tags['highway'] == "tertiary":
		if "highway" in segment['tags'] and segment['tags']['highway'] in ["service", "residential"]:
			segment['tags'].update(tags)

	# Only apply extra tunnel and bridge tags if tunnel/bridge already identified (from 'medium' attribute in road network)
	elif "tunnel" in tags or "bridge" in tags:
		if "tunnel" in tags and "tunnel" in segment['tags'] or "bridge" in tags and "bridge" in segment['tags']:
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

def simplify_geometry (line):

	i = 0
	previous_node = line[0]
	while i < len(line) - 2:
		i += 1
		if compute_distance(previous_node, line[i]) < simplify_margin:
			del line[i]
			i -= 1
		else:
			previous_node = line[i]

	if len(line) > 2 and compute_distance(line[-2], line[-1]) < simplify_margin:
		del line[-2]

	if len(line) < 2:
		message ("  *** Less than two coordinates in line\n")
	elif len(line) == 2 and line[0] == line[1] or compute_distance(line[0], line[1]) == 0:
		message ("  *** Zero length line\n")



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
	new_segment['extras']['KLIPP'] = "Ja"

	segments[new_segment_id] = new_segment
	sequences[ segment['sequence'] ].append(new_segment_id)
	parents[ segment['parent'] ].append(new_segment_id)

	segment['parent_end'] = clip_position
	segment['end_node'] = node_id
	segment['length'] = clip_length
	segment['extras']['KLIPP'] = "Ja"

	nodes[ new_segment['end_node'] ]['ways'].remove(segment['id'])
	nodes[ new_segment['end_node'] ]['ways'].add(new_segment_id)

	return new_segment



# Identify relevant segments and upate tags
# Clip segment if necessary. New clipped segments are appended at the end of sequence list

def update_segments_line (parent_sequence_id, tag_start, tag_end, direction, new_tags, new_extras):

	# Additional tags for tunnels and bridges, which already have 'tunnel' and 'bridge' tags
	if "tunnel" in new_tags or "bridge" in new_tags:
		for segment_id in parents[parent_sequence_id][:]:
			segment = segments[ segment_id ]
			if ("tunnel" in new_tags and "tunnel" in segment['tags'] or "bridge" in new_tags and "bridge" in segment['tags']) and \
					(not direction or segment['reverse'] == (direction == "backward")):

				margin = (segment['parent_end'] - segment['parent_start']) / segment['length'] * node_margin  # Meters
				if tag_start < segment['parent_start'] + margin and segment['parent_end'] - margin < tag_end or \
						segment['parent_start'] + margin < tag_start < segment['parent_end'] - margin or \
						segment['parent_start'] + margin < tag_end < segment['parent_end'] - margin:
					update_tags(segment, new_tags)
					segment['extras'].update(new_extras)

	else:
		for segment_id in parents[parent_sequence_id][:]:
			segment = segments[ segment_id ]
			margin = (segment['parent_end'] - segment['parent_start']) / segment['length'] * segment_margin  # Meters
			if tag_start < segment['parent_start'] + margin and segment['parent_end'] - margin < tag_end:
				update_tags(segment, new_tags)
				segment['extras'].update(new_extras)

			elif segment['parent_start'] + margin < tag_start and tag_end < segment['parent_end'] - margin:
				new_segment = clip_segment (segment, tag_start)
				clip_segment (new_segment, tag_end)
				update_tags(new_segment, new_tags)
				new_segment['extras'].update(new_extras)

			elif segment['parent_start'] + margin < tag_start < segment['parent_end'] - margin:
				new_segment = clip_segment (segment, tag_start)
				update_tags(new_segment, new_tags)
				new_segment['extras'].update(new_extras)

			elif segment['parent_start'] + margin < tag_end < segment['parent_end'] - margin:
				new_segment = clip_segment (segment, tag_end)
				update_tags(segment, new_tags)
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



# Traverse network to tag tunnels (or any other tag given by search_tag)
# Not currently used but kept for later

def traverse_and_tag (segment_id, search_tag, path_travelled, new_tags, new_extras):

	segment = segments[segment_id]

	if search_tag not in segment['tags']:  # No tunnel
		return
	
	if segment_id in path_travelled:  # Circular, segment already visited
		return

	segment['tags'].update(new_tags)
	segment['extras'].update(new_extras)
	new_path_travelled = copy.deepcopy(path_travelled)
	new_path_travelled.append(segment_id)

	for node_id in [segment['start_node'], segment['end_node']]:
		for next_segment_id in nodes[ node_id ]['ways']:
			if next_segment_id != segment_id:
				traverse_and_tag (next_segment_id, search_tag, new_path_travelled, new_tags, new_extras)



# Tag all connected tunnel segments with more tags (name etc)
# Not currently used but kept for later

def update_tunnels (parent_sequence_id, tag_position, new_tags, new_extras):

	if "tunnel" not in new_tags:
		return

	for segment_id in parents[parent_sequence_id]:
		segment = segments[segment_id]
		if segment['parent_start'] <= tag_position <= segment['parent_end']:
			traverse_and_tag (segment_id, "tunnel", [], new_tags, new_extras)



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
	if segment['highway'] not in ["Bilveg", "Rampe", u"Rundkjøring", "Gatetun"] and \
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

#	message ("\nRestriction: %i\n" % restriction_id)

	via_node_id = str(restriction['nodeid'])
	if via_node_id not in nodes:
#		message ("  *** 'Via' node %s of turn restriction %i not found\n" % (via_node_id, restriction_id))
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
#		message ("  *** 'From' segment %i of turn restriction %i not found\n" % (restriction['startpunkt']['veglenkesekvensid'], restriction_id))
		return
#	else:
#		message ("From: %s\n" % from_segments)

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
#		message ("  *** 'To' segment %i of turn restriction %i not found\n" % (restriction['sluttpunkt']['veglenkesekvensid'] ,restriction_id))
		return
#	else:
#		message ("To: %s\n" % to_segments)

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
#		message ("  *** Turn restriciton route for %i not found\n" % restriction_id)
		return

#	message ("Best route: %s\n" % best_route)

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
	for turn_restriction_id, turn_restriction in turn_restrictions.iteritems():
		if turn_restriction == new_restriction:
			found = True
			break

	if not found:
		turn_restrictions[ restriction_id ] = new_restriction
		nodes[ via_node_id ]['break'] = True

#	message ("Turn restriction ok %i\n" % restriction_id)



# Fetch road objects of given type for municipality from NVDB api
# Also update relevant segments with new tagging from objects
# In debug mode, saves input data to disc

def get_road_object (object_id, **kwargs):

	message("Merging object type #%s %s..." % (object_id, object_types[object_id]))

	object_url = server + "vegobjekter/" + object_id + "?inkluder=metadata,egenskaper,lokasjon&alle_versjoner=false&srid=wgs84&kommune=" + municipality
	if "property" in kwargs:
		object_url += "&egenskap=" + kwargs['property']

	returned = 1
	total_returned = 0
	objects = []
#	object_name = ""

	# Loop until no more pages to fetch

	while returned> 0:
		request = urllib2.Request(object_url, headers=request_headers)
		file = urllib2.urlopen(request)
		data = json.load(file)
		file.close()

		for road_object in data['objekter']:
			properties = Properties({})
			tags = {}
			extras = { 'ID': str(road_object['id']) }
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

				elif attribute['navn'] == u"Assosierte Tunnelløp":
					associated_tunnels = attribute['innhold']

			# Add tags from 1st pass of tunnels
			if object_id == "67" and road_object['id'] in tunnels:
				tags.update(tunnels[ road_object['id'] ]['tags'])

			tag_object(object_id, properties, tags)

			# Updae all connected tunnel segments
			if object_id == "581" and tags:
#				for location in locations:
#					update_tunnels (location['veglenkesekvensid'], location['relativPosisjon'], tags, extras)
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
						if mid_location['retning'] == "MED":
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
								if location[u'kjørefelt']:
									direction, code = get_direction(location[u'kjørefelt'][0])
								else:
									direction = ""
								update_segments_line (location['veglenkesekvensid'], location['startposisjon'], location['sluttposisjon'], \
									direction, tags, extras)
#							else:
#								message ("  *** Equal start and end positions in location - %i\n" % road_object['id'])

						# For pedestrian crossings, only accept "M" positions
						elif location['stedfestingstype'] == "Punkt" and ("sideposisjon" not in location or location['sideposisjon'] == "M"):  # or object_id == "96"
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
		debug_file.write(json.dumps(objects, indent=2))
		debug_file.close()



# Get tunnels and bridges from the non-segmentet road network api
# Note metering is relative to sequences, not super sequences


def get_bridges_and_tunnels():

	message("Merging tunnels and bridges...")

	object_url = url.replace("/segmentert", "")

	returned = 1
	total_returned = 0
	count_objects = 0

	# Loop until no more pages to fetch

	while returned > 0:
		request = urllib2.Request(object_url, headers=request_headers)
		file = urllib2.urlopen(request)
		data = json.load(file)
		file.close()

		for sequence in data['objekter']:
			for segment in sequence['veglenker']:
				medium = ""
				tags = {}
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

				if tags:
					count_objects += 1
					if sequence['veglenkesekvensid'] in sequences:
						for check_segment_id in sequences[ sequence['veglenkesekvensid'] ]:
							check_segment = segments[ check_segment_id ]
							margin = (check_segment['sequence_end'] - check_segment['sequence_start']) / check_segment['length'] * node_margin  # Meters
							if segment['startposisjon'] <= check_segment['sequence_start'] + margin and check_segment['sequence_end'] - margin <= segment['sluttposisjon']:
								check_segment['tags'].update(tags)
#					else:
#						message ("  *** No tunnel/bridge - %s-%i\n" % (sequence['veglenkesekvensid'], segment['veglenkenummer']))

		returned = data['metadata']['returnert']
		if "neste" in data['metadata']:
			object_url= data['metadata']['neste']['href']
		total_returned += returned

	message ("  %i tunnels and bridges\n" % count_objects)



# Generate tagging for road network segment and store in network data strucutre

def process_road_network (segment):

	if segment[u'detaljnivå'] != "Vegtrase" and segment['vegsystemreferanse']['vegsystem']['fase'] != "F":

		tags = {}
		extras = {}
		segment_id = segment['referanse']

		# Reverse way if backwards one way street

		if "superstedfesting" in segment and u"kjørefelt" in segment['superstedfesting']:
			lanes = segment['superstedfesting'][u'kjørefelt']
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

		if len(geometry) < 2 or len(geometry) == 2 and geometry[0] == geometry[1] or segment['lengde'] == 0:
#			message ("  *** Zero length segment excluded - %s\n" % segment_id)
			return

#		if segment['lengde'] < node_margin:
#			message ("  *** Very short segment %.2fm - %s\n" % (segment['lengde'], segment['referanse']))

		simplify_geometry(geometry)

		if segment['vegsystemreferanse']:
			highway_type = tag_highway(segment, lanes, tags, extras)
		else:
			highway_type = ""

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
					if u"adskilte_løp" in ref['strekning'] and ref['strekning'][u'adskilte_løp'] != "Nei":
						extras[u'ADSKILTE_LØP'] = "%s %s" % (ref['strekning'][u'adskilte_løp'], ref['strekning'][u'adskilte_løp_nummer'])
				else:
					extras['STED_SEGMENT'] = "%s (%.2fm)" % (segment['kortform'], segment['lengde'])
			else:
				extras['STED_SEGMENT'] = "%s (%.2fm)" % (segment['kortform'], segment['lengde'])

			extras['DATO_START'] = segment['metadata']['startdato'][:10]
			if "sluttdato" in segment:
				extras['DATO_SLUTT'] = segment['metadata']['sluttdato'][:10]

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

			if geometry_type == "line":
				highway_type = tag_highway(segment, [], segment_tags, segment_extras)  # No lanes
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
				'sequence': sequence_id,
				'tags': segment_tags,
				'extras': segment_extras,
				'reverse': False,
				'connection': False,
				'highway': highway_type,
				'geometry': geometry,
				'geotype': geometry_type
			} 

			update_tags(new_segment, tags)
			new_segment['extras'].update(extras)

			segments[segment_id] = new_segment
			if geometry_type == "line":
				if sequence_id not in sequences:
					sequences[sequence_id] = [segment_id]
					parents[sequence_id] = [segment_id]
				else:
					sequences[sequence_id].append(segment_id)
					parents[sequence_id].append(segment_id)



# Generate one osm tag for output

def tag_property (osm_element, tag_key, tag_value):

	tag_value = tag_value.strip()
	if tag_value:
		osm_element.append(ET.Element("tag", k=tag_key, v=tag_value))



# Output road network or objects to OSM file

def output_osm():

	message ("\nSaving file... ")

	osm_id = -1000
	count = 0

	osm_root = ET.Element("osm", version="0.6", generator="nvdb2osm", upload="false")

	# First ouput all start/end nodes

	for node_id, node in nodes.iteritems():
		osm_id -= 1
		osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node['point'][0]), lon=str(node['point'][1]))
		osm_root.append(osm_node)
		for key, value in node['tags'].iteritems():
			tag_property (osm_node, key, value)
		if debug:
			for key, value in node['extras'].iteritems():
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

			for key, value in segment['tags'].iteritems():
				tag_property (osm_way, key, value)
			if debug or object_tags:
				for key, value in segment['extras'].iteritems():
					if debug or object_tags and "VEGOBJEKT_" in key:
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
					for key, value in node[2].iteritems():
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

					for key, value in node[2].iteritems():
						tag_property (osm_node, key, value)

					for key, value in segment['tags'].iteritems():
						tag_property (osm_node, key, value)

					if debug or object_tags:
						for key, value in segment['extras'].iteritems():
							if debug or object_tags and "VEGOBJEKT_" in key:
								tag_property (osm_node, key, value)

	# Output restriction relations

	for restriction_id, restriction in turn_restrictions.iteritems():
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



# Create common nodes at intersections between ssegments for road objects
# Currently brute force method only, and only works for intersections where both segments start/end

def optimize_object_network ():

	# Semi-automated alternative, merging nodes at start/end of segments
	# Remaining duplicates to be merged in JOSM

	if len(segments) < 10000:

		message ("Merging road object nodes ...\n")

		i = 0
		for segment_id, segment in segments.iteritems():
			if segment['geotype'] == "line":

				i += 1
				start_node = segment['geometry'][0][0:2]
				end_node = segment['geometry'][-1][0:2]

				start_node_found = False
				end_node_found = False

				for node_id, node in nodes.iteritems():
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
		for segment_id, segment in segments.iteritems():
			if segment['geotype'] == "line":
				start_node = segment['geometry'][0][0:2]
				end_node = segment['geometry'][-1][0:2]
				segment['start_node'] = create_new_node ("", start_node, set([segment_id]))
				segment['end_node'] = create_new_node ("", end_node, set([segment_id]))



# Find first normal segment belonging to 'connection' segment and return it's id
# Not used but kept for later

def find_connected_segment (segment_id):

	segment = segments[segment_id]
	message ("\r%s" % segment_id)

	# First check ways connected backwards, then forwards if necessary

	for node_id in [segment['start_node'], segment['end_node']]:
		last_segment_id = segment_id
		last_segment = segment
		last_node_id = node_id
		checked_segments = [ last_segment_id ]

		check_next = True
		while check_next:
			check_next = False  # Default

			if len(nodes[ last_node_id ]['ways']) != 2:
				continue

			for check_segment_id in nodes[ last_node_id ]['ways']:
				check_segment = segments[ check_segment_id ]
				if check_segment_id not in checked_segments and checked_segment['highway'] == last_segment['highway']:
					if check_segment['connection']:
						if last_node_id == check_segment['start_node']:
							last_node_id = check_segment['end_node']
						else:
							last_node_id = check_segment['start_node']
						check_next = True
					last_segment_id = check_segment_id
					last_segment = check_segment
					checked_segments.append(check_segment_id)
					break

		if last_segment_id != segment_id and not last_segment['connection']:
			return last_segment_id

	return None



# Prepares road network and road objects for output
# 1) Consolidates tagging at intersection nodes
# 2) Simplifies network by combining consecutive segments into longer ways
# 3) Builds ways data strucutre for output

def optimize_network ():

	# For all connection segments, find attached segment and put connection segment into same sequence

	if longer_ways:

		for sequence_id, sequence_segment in sequences.iteritems():
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
							segment['extras']['KONNEKTOR_KOPI'] = "Ja"

							if connected_segment['sequence'] != sequence_id:
								segment['sequence'] = connected_segment['sequence']
								sequences[ connected_segment['sequence'] ].append(segment_id)
								sequence_segment.remove(segment_id)
								segment['extras']['KONNEKTOR_SEKVENS'] = str(connected_segment['sequence'])


	# Copy node tags to node dict

	for segment_id, segment in segments.iteritems():
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

	# Make longer ways

	if longer_ways:

		for sequence_id, sequence_segments in sequences.iteritems():
			remaining_segments = copy.deepcopy(sequence_segments)

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
							if (abs(angle) < angle_margin or segment['connection'] or segments[ way[-1] ]['connection']):
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
							if abs(angle) < angle_margin or segment['connection'] or segments[ way[0] ]['connection']:
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
		for segment_id, segment in segments.iteritems():
			if segment['geotype'] == "line":
				ways.append([segment_id])

	# Add remaining points

	for segment_id, segment in segments.iteritems():
		if segment['geotype'] == "point":
			ways.append([segment_id])



# Fix errors in api
# Remove duplicate segments from road network

def fix_network():

	message ("Removing duplicate segments... ")

	count_removed = 0

	for segment_id in segments.keys():
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



# Fetch road network or road objects from NVDB, including paging
# In debug mode, saves input data to disc

def get_data(url):

	message ("Loading NVDB data...\n")

	returned = 1
	total_returned = 0

	if debug:
		debug_file = open("nvdb_%s_input.json" % function, "w")
		debug_file.write("[\n")

	# Loop until no more pages to fetch

	while returned > 0:

		request = urllib2.Request(url, headers=request_headers)
		file = urllib2.urlopen(request)
		data = json.load(file)
		file.close()

		if debug:
			debug_file.write(json.dumps(data, indent=2))

		for record in data['objekter']:
			if "geometri" in record:
				if "vegobjekt" in url:
					process_road_object(record)
				elif "vegnett" in url:
					process_road_network(record)

		returned = data['metadata']['returnert']
		url = data['metadata']['neste']['href']
		total_returned += returned
		message ("\r%i" % total_returned)

		if debug and returned > 0:
			debug_file.write(",\n")

	if debug:
		debug_file.write("]\n")
		debug_file.close()

	message("\rDone processing %i road objects/segments\n" % total_returned)



# Load data from api

def load_data (url):

	request = urllib2.Request(url, headers=request_headers)
	file = urllib2.urlopen(request)
	data = json.load(file)
	file.close()

	return data



# Main program

if __name__ == '__main__':

	start_time = time.time()
	message ("\nnvdb2osm v%s\n\n" % version)

	# Get database status

	data = load_data(server + "status")
	message ("Server:         %s\n" % server)
	message ("Data catalogue: %s, %s\n" % (data['datagrunnlag']['datakatalog']['versjon'], data['datagrunnlag']['datakatalog']['dato']))
	message ("Last update:    %s\n\n" % data['datagrunnlag']['sist_oppdatert'][:10])

	# Get municipalities and road object types

	data = load_data("https://ws.geonorge.no/kommuneinfo/v1/kommuner")
	municipalities = {}
	for entry in data:
		municipalities[ entry['kommunenummer'] ] = entry['kommunenavn']

	data = load_data(server + "vegobjekttyper")
	object_types = {}
	for entry in data:
		object_types[ str(entry['id']) ] = entry['navn']
	del data

	# Build query

	url = ""
	municipality = ""
	object_type = ""

	if len(sys.argv) > 2:
		if (sys.argv[1] == "-vegnett") and len(sys.argv) >= 3 and sys.argv[2].isdigit():
			municipality = sys.argv[2]
			url = server + "vegnett/veglenkesekvenser/segmentert?srid=wgs84&kommune=" + municipality

		elif (sys.argv[1] == "-vegref") and (len(sys.argv) >= 3):
			url = server + "vegnett/veglenkesekvenser/segmentert?srid=wgs84&vegsystemreferanse=" + sys.argv[2]
			include_objects = False

		elif (sys.argv[1] == "-vegobjekt") and (len(sys.argv) >= 4) and sys.argv[2].isdigit() and sys.argv[3].isdigit():
			object_type = sys.argv[2]
			municipality = sys.argv[3]
			url = server + "vegobjekter/" + sys.argv[2] + "?inkluder=metadata,egenskaper,geometri,lokasjon,vegsegmenter&alle_versjoner=false&srid=wgs84&kommune=" + municipality

		elif (sys.argv[1] == "-vegobjekt") and (len(sys.argv) >= 3) and sys.argv[2].isdigit():
			object_type = sys.argv[2]
			url = server + "vegobjekter/" + sys.argv[2] + "?inkluder=metadata,egenskaper,geometri,lokasjon,vegsegmenter&alle_versjoner=false&srid=wgs84"

		elif (sys.argv[1] == "-vegurl") and ("vegvesen.no" in sys.argv[2]):
			url = sys.argv[2] + "&srid=wgs84"

		if "-segmentert" in sys.argv:
			longer_ways = False
			include_objects = False

		if "-debug" in sys.argv:
			debug = True

		if "vegnett" in url:
			function = "vegnett"
		elif "vegobjekt" in url:
			function = "vegobjekt"
			object_tags = True
		else:
			function = ""

	# Check parameters and set output filename

	output_filename = "nvdb"

	if url and municipality:
		if municipality in municipalities:
			message ("Municipality:   #%s %s\n" % (municipality, municipalities[municipality]))
			if not object_type:
				output_filename += "_" + municipality + "_" + municipalities[municipality].replace(" ", "_")
		else:
			message ("*** Municipality %s not found\n" % municipality)
			url = ""

	if url and object_type:
		if object_type in object_types:
			message ("Road object:    #%s %s\n" % (object_type, object_types[object_type]))
			output_filename += "_" + object_type + "_" + object_types[object_type].replace(" ", "_")
		else:
			message ("*** Road object type %s not found\n" % object_type)
			url = ""

	if output_filename == "nvdb":
		output_filename += "_" + function

	if include_objects and function == "vegnett" or longer_ways:
		output_filename = output_filename + ".osm"
	else:
		output_filename = output_filename + "_segmentert.osm"

	for argument in sys.argv[3:]:
		if ".osm" in argument.lower():
			output_filename = argument.replace(" ", "_")

	if url:
		message("Query:          %s\n" % url)
		message("Ouput filename: %s\n\n" % output_filename)
	else:
		message("\nPlease provide parameters in one of the following ways:\n")
		message('  nvdb2osm -vegnett <nnnn>  -->  Road network for municipality number (4 digits)\n')
		message('  nvdb2osm -vegref <reference>  -->  Road network for road reference code (e.g. "0400Ea6")\n')		
		message('  nvdb2osm -vegobjekt <nnn>  -->  Road object number (2-3 digits) for entire country\n')
		message('  nvdb2osm -vegobjekt <nnn> <mmmm>  -->  Road object number (2-3 digits) for municipality number (4 digits)\n')
		message('  nvdb2osm -url "<api url string>"  -->  Any api generated from vegkart.no (UTM bounding box not supported, wgs84 appended)\n')
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

	get_data(url)

	if function == "vegnett":
		fix_network()
		get_bridges_and_tunnels()

	# Read objects

	if function == "vegnett" and include_objects:

		# Points
		get_road_object ("103")  # Speed bumps
		get_road_object ("174")  # Pedestrian crossing (sometimes incorrect segment i NVDB)
		get_road_object ("100")  # Railway crossing
		get_road_object ("89")   # Traffic signal
		get_road_object ("22")   # Cattle grid
		get_road_object ("607")  # Barrier
		get_road_object ("47")   # Passing place
		get_road_object ("64")   # Ferry terminal
		get_road_object ("37")   # Junction
		
		# Ways
		get_road_object ("581")  # Tunnel node - 1st pass
		get_road_object ("67")   # Tunnel ways - 2nd pass
		get_road_object ("60")   # Bridges - uferdig
		get_road_object ("595")  # Motorway, motorroad
		get_road_object ("538")  # Street names
		get_road_object ("105")  # Maxspeeds
		get_road_object ("241")  # Surface
		get_road_object ("821")  # Functional road class
		get_road_object ("856")  # Access restrictions
		get_road_object ("107")  # Weather restrictions
		get_road_object ("591")  # Maxheight
		get_road_object ("904")  # Maxweight, maxlength
		
		get_road_object ("96", property="(5530=7643)")  # Stop sign
		
		get_road_object ("573")  # Turn restrictions
		
	if function == "vegobjekt":
		optimize_object_network()

	optimize_network()

	output_osm()

	message ("Time: %i seconds (%i segments per second)\n\n" % ((time.time() - start_time), (len(segments) / (time.time() - start_time))))
