#!/usr/bin/env python
# -*- coding: utf8

# NVDB2OSM.PY
# Converts road objects and road networks from NVDB to OSM
# Usage:
# 1) nvdb2osm -vo <vegobjektkode> [-k <kommune>] > outfile.osm  --> Produces osm file with all road objects of a given type (optionally within a given municipality)
# 2) nvdb2osm -vn -k <kommune> > outfile.osm  --> Produces osm file with road network for a given municipality
# 3) nvdb2osm -vr <vegreferanse> > outfile.osm  --> Produces osm file with road network for given road reference code
# 4) nvdb2osm -vu "<http string from vegnett.no>"" > outfile.osm  --> Produces osm file defined by given NVDB http api call from vegkart.no.
#       "&srid=wgs84" automatically added. Bounding box only supported for wgs84 coordinates, not UTM from vegkart.no. 

import json
import urllib2
import sys
import cgi


version = "0.2.0"

road_category = {
	'E': {'name': 'Europaveg', 'tag': 'trunk'},
	'R': {'name': 'Riksveg', 'tag': 'trunk'},
	'F': {'name': 'Fylkesveg', 'tag': 'secondary'},
	'K': {'name': 'Kommunal veg', 'tag': 'residential'},
	'P': {'name': 'Privat veg', 'tag': 'service'},
	'S': {'name': 'Skogsbilveg', 'tag': 'track'}
}

road_status = {
	'V': 'Eksisterende veg',
	'W': 'Midlertidig veg',
	'T': 'Midlertidig status bilveg',
	'S': 'Eksisterende ferjestrekning',
	'G': 'Gang-/sykkelveg',
	'U': 'Midlertidig status gang-/sykkelveg',
	'B': 'Beredskapsveg',
	'M': 'Serviceveg',
	'X': u'Rømningstunnel',
	'A': 'Anleggsveg',
	'H': 'Gang-/sykkelveg anlegg',
	'P': 'Vedtatt veg',
	'E': 'Vedtatt ferjestrekning',
	'Q': 'Vedtatt gang-/sykkelveg'
}

road_section = {
	'Hovedparseller': (1, 49),
	'Armer': (50, 69),
	'Ramper': (70, 199),
	u'Rundkjøringer': (400, 599),
	u'Skjøteparseller': (600, 699),
	'Trafikklommer, rasteplasser': (800, 998)
}

cycleway_section = {
	u'Høyre for hovedparseller': (1, 49),
	u'Høyre for armer': (50, 69),
	u'Høyre for ramper': (70, 149),
	'Armer': (150, 200),
	'Venstre for hovedparseller': (201, 249),
	'Venstre for armer': (250, 269),
	'Venstre for ramper': (270, 349),
	'Ramper': (350, 399)
}

theme = {
	7001: 'Vegsenterlinje',
	7004: 'Svingekonnekteringslenke',
	7012: 'Vegtrase',
	7011: u'Kjørebane',
	7010: u'Kjørefelt',
	7201: 'Bilferjestrekning',
	7042: 'Gang Sykkelveg Senterlinje',
	7043: 'Sykkelveg Senterlinje',
	7046: 'Fortau',
	6304: u'Frittstående trapp'
}

medium = {
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


# Generate one osm tag

def tag_property (key, value):

	value = value.strip()
	if value:
		key = cgi.escape(key.encode('utf-8'), True)
		value = cgi.escape(value.encode('utf-8'), True)
		print ("    <tag k='%s' v='%s' />" % (key, value))


# Generate road number

def get_ref (category, number):

	if category == "E":
		ref = "E " + str(number)
	elif category in ["R", "F"]:
		ref = str(number)
	else:
		ref = ""

	return ref


# Find road section

def get_section (section_id, theme_id):

	global road_section
	global cycleway_section

	if theme_id in [7042, 7943]:

		for section_name, section_interval in cycleway_section.iteritems():
			if section_id >= section_interval[0] and section_id <= section_interval[1]:
				return section_name	

	else:

		for section_name, section_interval in road_section.iteritems():
			if section_id >= section_interval[0] and section_id <= section_interval[1]:
				return section_name

	return ""


# Decode lanes

def process_lanes (lane_codes):

	forward_lanes = 0
	backward_lanes = 0
	forward_turn = ""
	backward_turn = ""
	forward_psv = ""
	backward_psv = ""
	forward_cycleway = False
	backward_cycleway = False

	# Loop all lanes and build turn:lane tags + count lanes

	split_lanes = lane_codes.split("#")

	for lane in split_lanes:

		turn = ""

		if (len(lane) > 1) and (lane[1] in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]):
			side = lane[0:2]
			if len(lane) > 2:
				turn = lane[2].upper()
		else:
			side = lane[0]
			if len(lane) > 1:
				turn = lane[1].upper()

		# Odd lanes forward

		if side[-1] in ["1", "3", "5", "7", "9"]:
			
			if turn == "V":
				forward_turn = "|left" + forward_turn
				forward_psv = "|" + forward_psv
				forward_lanes += 1
			elif turn == "H":
				forward_turn = forward_turn + "|right"
				forward_psv = forward_psv + "|"
				forward_lanes += 1
			elif turn == "K":
				forward_turn = forward_turn + "|"
				forward_psv = forward_psv + "|designated"
				forward_lanes += 1
			elif turn == "S":
				forward_cycleway = True
			else:
				forward_turn = forward_turn + "|"
				forward_psv = forward_psv + "|"
				forward_lanes += 1

		# Even lanes backward (reverse left/right)

		else:

			if turn == "V":
				backward_turn = "|left" + backward_turn
				backward_psv = "|" + backward_psv
				backward_lanes += 1
			elif turn == "H":
				backward_turn = backward_turn + "|right"
				backward_psv = backward_psv + "|"
				backward_lanes += 1
			elif turn == "K":
				backward_turn = backward_turn + "|"
				backward_psv = backward_psv + "|designated"
				backward_lanes += 1				
			elif turn == "S":
				backward_cycleway = True
			else:
				backward_turn = backward_turn + "|"
				backward_psv = backward_psv + "|"
				backward_lanes += 1

	# Produce turn:lane and lanes tags. One-way if lanes are in one direction only. Lanes tagging if more than one lane.

	forward_turn = forward_turn[1:]
	backward_turn = backward_turn[1:]

	if not(forward_turn.lstrip("|")):
		forward_turn = ""
	if not(backward_turn.lstrip("|")):
		backward_turn = ""

	forward_psv = forward_psv[1:]
	backward_psv = backward_psv[1:]

	if not(forward_psv.lstrip("|")):
		forward_psv = ""
	if not(backward_psv.lstrip("|")):
		backward_psv = ""
	
	if (forward_lanes > 0) and (backward_lanes > 0):

		if (forward_lanes > 1) and (backward_lanes > 1):
			tag_property ("turn:lanes:forward", forward_turn)
			tag_property ("turn:lanes:backward", backward_turn)

		if (forward_psv == "designated") and (backward_psv == "designated"):
			tag_property ("psv", "designated")
			tag_property ("motorcar", "no")
		else:
			tag_property ("psv:lanes:forward", forward_psv)
			tag_property ("psv:lanes:backward", backward_psv)
			tag_property ("motorcar:lanes:forward", forward_psv.replace("designated","no"))
			tag_property ("motorcar:lanes:backward", backward_psv.replace("designated","no"))

		if forward_turn or backward_turn or forward_psv or backward_psv or (forward_lanes > 1) or (backward_lanes > 1):
			tag_property ("lanes", str(forward_lanes + backward_lanes))
			if forward_lanes != backward_lanes:
				tag_property ("lanes:forward", str(forward_lanes))
				tag_property ("lanes:backward", str(backward_lanes))

	elif forward_lanes > 0:

		if forward_lanes > 1:
			tag_property ("turn:lanes", forward_turn)

		if forward_psv == "designated":
			tag_property ("psv", "designated")
			tag_property ("motorcar", "no")
		else:
			tag_property ("psv:lanes", forward_psv)
			tag_property ("motorcar:lanes", forward_psv.replace("designated","no"))

		if (forward_turn and forward_lanes > 1) or (forward_psv and forward_psv != "designated") or (forward_lanes > 1):
			tag_property ("lanes", str(forward_lanes))

		tag_property ("oneway", "yes")

	elif backward_lanes > 0:

		if backward_lanes > 1:
			tag_property ("turn:lanes", backward_turn)

		if backward_psv == "designated":
			tag_property ("psv", "designated")
			tag_property ("motorcar", "no")
		else:
			tag_property ("psv:lanes", backward_psv)
			tag_property ("motorcar:lanes", backward_psv.replace("designated","no"))

		if (backward_turn and backward_lanes > 1) or (backward_psv and backward_psv != "designated") or (backward_lanes > 1):
			tag_property ("lanes", str(backward_lanes))

		tag_property ("oneway", "yes")

	# Produce cycleway lane tags

	if forward_cycleway and backward_cycleway:
		tag_property ("cycleway", "lane")
	elif forward_cycleway:
		tag_property ("cycleway:right", "lane")
	elif backward_cycleway:
		tag_property ("cycleway:left", "lane")


# Generate list of (x,y) tuples from wkt

def unpack_wkt (wkt):

	geometry = []

	wkt_points = wkt.split(", ")

	for point in wkt_points:
		coordinate = point.lstrip("(").rstrip(")").split(" ")
		geometry.append((coordinate[0], coordinate[1]))

	return geometry


# Generate geometry tagging

def process_geometry (wkt, reverse):

	global osm_id
	global end_tag
	global debug

	start = wkt.find("(")
	geometry_type = wkt[:start - 1]
	wkt = wkt[start + 1:-1]

	wkt_split = wkt.split("), (")
	wkt_count = len(wkt_split)

	for wkt_part in wkt_split:

		wkt_part = wkt_part.lstrip("(").rstrip(")")
		geometry = unpack_wkt(wkt_part)

		if not(geometry_type in ["POINT", "POINT Z", "MULTIPOINT", "MULTIPOINT Z"]):

			if geometry_type == "POLYGON":
				geometry_length = len(geometry) - 1
			else:
				geometry_length = len(geometry)

			# Generate nodes

			for i in range(geometry_length):
				osm_id -= 1
				print ("  <node id='%i' action='modify' visible='true' lat='%s' lon='%s' />" % (osm_id, geometry[i][0], geometry[i][1]))

			# Generate way and reference to nodes in way

			end_tag = "way"
			osm_id -= 1
			print ("  <way id='%i' action='modify' visible='true'>" % osm_id)

			for i in range(geometry_length):
				if reverse:
					ref_id = osm_id + i + 1
				else:
					ref_id = osm_id + geometry_length - i
				print ("    <nd ref='%i' />" % ref_id)

 			# Polygon: Reference back to first node to make closed way

			if geometry_type == "POLYGON":
				if reverse:
					ref_id = osm_id + 1
				else:
					ref_id = osm_id + geometry_length
				print ("    <nd ref='%i' />" % ref_id)

		else:
			# Generate node

			end_tag = "node"
			osm_id -= 1
			print ("  <node id='%i' action='modify' visible='true' lat='%s' lon='%s'>" % (osm_id, geometry[0][0], geometry[0][1]))

		if debug:
			tag_property ("GEOMETRI_TYPE", geometry_type)
			if reverse:
				tag_property ("REVERSE", "Ja")

		# For multiline end way if not last way in multiline

		wkt_count -= 1
		if wkt_count > 0: 
			print ("  </%s>" % (end_tag))


# Vegobjekt

def process_vegobjekt (data):

	global debug

	for road_object in data['objekter']:

		if "geometri" in road_object:

			process_geometry (road_object['geometri']['wkt'], reverse=False)

			if "egenskaper" in road_object:
				for attribute in road_object['egenskaper']:
					if not(attribute['datatype_tekst'] in ["GeomPunkt", "GeomFlate", "GeomLinje eller Kurve"]):

						key = attribute['navn'].replace(" ","_").replace(".","").replace(",","")
						if attribute['datatype_tekst'] == "Tall":
							value = str(attribute['verdi'])
						elif attribute['datatype_tekst'] == "FlerverdiAttributt, Tekst":
							value = "#" + str(attribute['enum_id']) + " " + attribute['verdi']
						elif attribute['datatype_tekst'] == "Flerverdiattributt, Tall":
							value = "#" + str(attribute['enum_id']) + " " + str(attribute['verdi'])
						else:
							value = attribute['verdi']
						tag_property (key.upper(), value)

					elif debug:
						tag_property ("GEOMETRI", attribute['datatype_tekst'])

					if (attribute['navn'] == "Envegsregulering") and (attribute['verdi'][0:5] == "Enveg"):
						tag_property ("oneway", "yes")

			if ("lokasjon" in road_object) and ("vegreferanser" in road_object['lokasjon']):

				ref = road_object['lokasjon']['vegreferanser'][0]

				# Set key according to status (proposed, construction, existing)

				if ref['status'] in ["A", "H"]:
					tag_property ("highway", "construction")
					tag_key = "construction"
				elif ref['status'] in ["P", "Q"]:
					tag_key = "proposed:highway"
				elif ref['status'] == "E":
					tag_key = "proposed:route"
				elif ref['status'] == "S":
					tag_key = "route"
				else:
					tag_key = "highway"

				if ref['status'] in ["G", "U", "H", "Q"]:  # Cycleway
					tag_property (tag_key, "cycleway")

				elif ref['status'] in ["S", "E"]:  # Ferry
					tag_property (tag_key, "ferry")
					tag_property ("ref", get_ref(ref['kategori'], ref['nummer']))

				else:   # Regular highways
					if ref['hp'] / 100 == 8:  # Trafikklommer/rasteplasser
						tag_property (tag_key, "unclassified")
					else:

						if (ref['kategori'] in ["E", "R", "F"]) and (ref['hp'] >= 70) and (ref['hp'] <= 199):  # Ramper
							link = "_link"
						else:
							link = ""

						if (ref['fylke'] == 50) and (ref['kategori'] == "F") and (ref['nummer'] < 1000):  # Trøndelag
							tag_property (tag_key, "primary" + link)
						else:
							tag_property (tag_key, road_category[ref['kategori']]['tag'] + link)

						tag_property ("ref", get_ref(ref['kategori'], ref['nummer']))

					if ref['status'] == "X":  # Rømningstunnel
						tag_property ("tunnel", "yes")
						tag_property ("layer", "-1")

			if debug:

				tag_property ("ID", str(road_object['id']))

				if "egengeometri" in road_object['geometri']:
					tag_property ("EGENGEOMETRI", "Ja")

				if "metadata" in road_object:
					tag_property ("VEGOBJEKTTYPE", road_object['metadata']['type']['navn'])
					tag_property ("SIST_MODIFISERT", road_object['metadata']['sist_modifisert'][:10])

				if "lokasjon" in road_object:
					i = 0
					for stedfesting in road_object['lokasjon']['stedfestinger']:
						i += 1
						tag_property ("VEGLENKE_" + str(i), str(stedfesting['veglenkeid']))
						tag_property ("POSISJON_" + str(i), stedfesting['retning'] + " " + stedfesting['kortform'])

			print ("  </%s>" % end_tag)  # /node or /way


# Vegnett

def process_vegnett (data):

	global debug

	for lenke in data['objekter']:

		if "geometri" in lenke:

			if ((u"topologinivå" in lenke) and (lenke[u'topologinivå'] > 0)) or not(u"topologinivå" in lenke):

				# Reverse way if backwards one way street

				if ("felt" in lenke) and (lenke['felt'][0] in ["2", "4", "6", "8"]):  # Todo: Double digit lanes
					process_geometry (lenke['geometri']['wkt'], reverse=True)
				else:
					process_geometry (lenke['geometri']['wkt'], reverse=False)

				if "vegreferanse" in lenke:

					ref = lenke['vegreferanse']

					# Set key according to status (proposed, construction, existing)

					if ref['status'] in ["A", "H"]:
						tag_property ("highway", "construction")
						tag_key = "construction"
					elif ref['status'] in ["P", "Q"]:
						tag_key = "proposed:highway"
					elif ref['status'] == "E":
						tag_key = "proposed:route"
					elif ref['status'] == "S":
						tag_key = "route"
					else:
						tag_key = "highway"

					if (lenke['temakode'] in [7001, 7011, 7010]) and (ref['status'] != "G"):  # Regular highways (excluding "kjørefelt")

						if ref['hp'] / 100 == 8:  # Trafikklommer/rasteplasser
							tag_property (tag_key, "unclassified")
						else:

							if (ref['kategori'] in ["E", "R", "F"]) and (ref['hp'] >= 70) and (ref['hp'] <= 199):  # Ramper
								link = "_link"
							else:
								link = ""

							if (ref['fylke'] == 50) and (ref['kategori'] == "F") and (ref['nummer'] < 1000):  # Trøndelag
								tag_property (tag_key, "primary" + link)
							else:
								tag_property (tag_key, road_category[ref['kategori']]['tag'] + link)

							tag_property ("ref", get_ref(ref['kategori'], ref['nummer']))

						if "felt" in lenke:		
							process_lanes (lenke['felt'])

						if lenke['temakode'] == 7010:
							tag_property ("FIXME", 'Consider replacing with "turn:lanes"')

					elif lenke['temakode'] == 7042:  # Combined cycleway/footway
						if ref['kategori'] != "P":
							tag_property (tag_key, "cycleway")
							tag_property ("foot", "designated")
						else:
							tag_property (tag_key, "footway")
							tag_property ("bicycle", "yes")

					elif lenke['temakode'] == 7043:  # Express cycleway
						tag_property (tag_key, "cycleway")
						if ("felt" in lenke) and (lenke['felt'] == "1S#2S"):
							tag_property ("lanes", "2")

					elif lenke['temakode'] == 7201:  # Ferry
						tag_property (tag_key, "ferry")
						tag_property ("ref", get_ref(ref['kategori'], ref['nummer']))

					elif lenke['temakode'] == 7046:  # Footway
						tag_property (tag_key, "footway")
						tag_property ("footway", "sidewalk")

					elif lenke['temakode'] == 6304:  # Stairs
						tag_property (tag_key, "stairs")

					elif ref['status'] == "G":  # Cycleways which are coded as regular highways, always crossings
						tag_property (tag_key, "footway")
						tag_property ("footway", "crossing")

#					elif lenke['temakode'] == 7010:  # "Kjørefelt"
#						tag_property ("oneway" , "yes")

				# Tunnels, bridges and roundabouts

				if lenke['medium'] in ["U", "W", "J"]:
					tag_property ("tunnel", "yes")
					tag_property ("layer", "-1")

				elif lenke['medium'] == "B":
					tag_property ("tunnel", "building_passage")

				elif lenke['medium'] == "L":
					tag_property ("bridge", "yes")
					tag_property ("layer", "1")

				if lenke['typeVeg'] == u"rundkjøring":
					tag_property ("junction", "roundabout")

			# Produce centerline ways for debugging

			elif debug_trase:
				process_geometry (lenke['geometri']['wkt'], reverse=False)
			else:
				continue

			# Produce tags for debugging

			if debug:

				if "egengeometri" in lenke['geometri']:
					tag_property ("EGENGEOMETRI", "Ja")

				tag_property ("ID", str(lenke['veglenkeid']))
				tag_property ("STARTPOSISJON", str(lenke['startposisjon']))
				tag_property ("SLUTTPOSISJON", str(lenke['sluttposisjon']))
				tag_property ("MEDIUM", "#" + lenke['medium'] + " " + medium[lenke['medium']])
				tag_property ("TEMAKODE", "#" + str(lenke['temakode']) + " " + theme[lenke['temakode']])
				tag_property ("TYPEVEG", lenke['typeVeg'])
				tag_property ("STARTNODE", lenke['startnode'])
				tag_property ("SLUTTNODE", lenke['sluttnode'])				

				if u"topologinivå" in lenke:
					tag_property (u"TOPOLOGINIVÅ", "#" + str(lenke[u'topologinivå']) + " " + lenke[u"topologinivå_tekst"])
#					if lenke[u'topologinivå'] > 0:
#						tag_property ("oneway", "yes")

				if "foreldrelenkeid" in lenke:
					tag_property ("FORELDRELENKE", str(lenke["foreldrelenkeid"]))

				if "felt" in lenke:
					tag_property ("FELT", lenke['felt'])

				if "metadata" in lenke:
					tag_property ("STARTDATO", lenke['metadata']['startdato'][:10])

				if "vegreferanse" in lenke:
					ref = lenke['vegreferanse']
					tag_property ("VEGREFERANSE", ref['kortform'])
					tag_property ("STATUS", "#" + ref['status'] + " " + road_status[ref['status']])
					tag_property ("KATEGORI", "#" + ref['kategori'] + " " + road_category[ref['kategori']]['name'])
					tag_property ("HP", "#" + str(ref['hp']) + " " + get_section (ref['hp'], lenke['temakode']))

			print ("  </%s>" % end_tag)  # /node or /way


# Main program

if __name__ == '__main__':

	filename = ""
	if len(sys.argv) > 2:
		if (sys.argv[1] == "-vn") and (len(sys.argv) == 4) and (sys.argv[2] == "-k") and sys.argv[3].isdigit():
			filename = "https://www.vegvesen.no/nvdb/api/v2/vegnett/lenker?srid=wgs84&kommune=" + sys.argv[3]
		elif (sys.argv[1] == "-vr") and (len(sys.argv) == 3):
			filename = "https://www.vegvesen.no/nvdb/api/v2/vegnett/lenker?srid=wgs84&vegreferanse=" + sys.argv[2]
		elif (sys.argv[1] == "-vo") and (len(sys.argv) == 3) and sys.argv[2].isdigit():
			filename = "https://www.vegvesen.no/nvdb/api/v2/vegobjekter/" + sys.argv[2] + "?inkluder=metadata,egenskaper,geometri,lokasjon&srid=wgs84"
		elif (sys.argv[1] == "-vo") and (len(sys.argv) == 5) and sys.argv[2].isdigit() and (sys.argv[3] == "-k") and sys.argv[4].isdigit():
			filename = "https://www.vegvesen.no/nvdb/api/v2/vegobjekter/" + sys.argv[2] + "?inkluder=metadata,egenskaper,geometri,lokasjon&srid=wgs84&kommune=" + sys.argv[4]
		elif (sys.argv[1] == "-vu") and ("vegvesen.no/nvdb/api/v2/" in sys.argv[2]):
			filename = sys.argv[2] + "&srid=wgs84"

	if filename:
		sys.stderr.write("Generating osm file for: %s ...\n" % filename)
	else:
		sys.stderr.write("Please provide parameters in one of the following ways:\n")
		sys.stderr.write('  nvdb2osm -vn -k <nnnn> > outfile.osm  -->  Road network for municipality number (4 digits)\n')
		sys.stderr.write('  nvdb2osm -vr <reference> > outfile.osm  -->  Road network for road reference code (e.g. "0400Ea6")\n')		
		sys.stderr.write('  nvdb2osm -vo <nnn> > outfile.osm  -->  Road object number (2-3 digits) for entire country\n')
		sys.stderr.write('  nvdb2osm -vo <nnn> -k <mmmm> > outfile.osm  -->  Road object number (2-3 digits) for municipality number (4 digits)\n')
		sys.stderr.write('  nvdb2osm -vu "<api url string>" > outfile.osm  -->  Any api generated from vegkart.no (UTM bounding box not supported, wgs84 appended)\n')
		sys.exit()

	request_headers = {
		"X-Client": "nvdb2osm",
		"X-Kontaktperson": "nkamapper@gmail.com"
	}

	osm_id = -1000
	returnert = 1
	total_returnert = 0
	debug = False
	debug_trase = False

	print ("<?xml version='1.0' encoding='UTF-8'?>")
	print ("<osm version='0.6' generator='nvdb2osm v%s' upload='false'>" % version)

	# Loop until no more pages to fetch

	while returnert > 0:

		request = urllib2.Request(filename, headers=request_headers)
		file = urllib2.urlopen(request)
		data = json.load(file)
		file.close()

		if "vegobjekter" in filename:
			process_vegobjekt(data)
		elif "vegnett" in filename:
			process_vegnett(data)

		returnert = data['metadata']['returnert']
		filename = data['metadata']['neste']['href']
		total_returnert += returnert

	print ("</osm>")

	sys.stderr.write("Done processing %i road objects/links\n" % total_returnert)
