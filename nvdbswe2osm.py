#!/usr/bin/env python3
# -*- coding: utf8

# nvdbswe2osm
# Converts NVDB data to OSM.
# Program loads geojson file for municipality.
# Order "homogeniserad" file from Lastkajen at Trafikverket and convert to geojson in QGIS or elsewehere.
# No dependencies beyond standard python.


import json
import sys
import copy
import math
import time
from xml.etree import ElementTree as ET


version = "0.3.0"

debug = False				# Add extra tags for debugging/testing

angle_margin = 45.0			# Maximum turn at intersection before highway is split into new way (degrees).

bridge_margin = 50.0		# Bridges over this length is always tagged as bridge, instead of tunnel duct for road underneath (meters)

coordinate_decimals = 7 	# Number of decimals in coordinates

simplify_method = "refname"	# Options for generating long ways before output: "recursive", "route" or "refname"

simplify_factor = 0.2		# Minimum deviation permitted for node in segment polygons (meters).
							# Set to 0 to avoid simplifying polygons.

segment_output = False		# When true: Output each highway segments as in input file, without creating longer ways


# Conversion table for nvdb attribute names, to make them more readable in code.
# Some of them are not used.

nvdb_attributes = {
	'Hogst_55_30':					'Begränsat axel-boggitryck/Högsta tillåtna tryck',
	'L_Blandskydd_2':				'Bländskydd(V)',
	'R_Blandskydd_2':				'Bländskydd(H)',
	'Ident_191':					'Bro och tunnel/Identitet',
	'Langd_192':					'Bro och tunnel/Längd',
	'Namn_193':						'Bro och tunnel/Namn',
	'konst_190':					'Bro och tunnel/Konstruktion',
	'Brunn___Slamsugning_2':		'Brunn-slamsugning',
	'L_Mater_301':					'Bullerskydd-väg/Materialtyp(V)',
	'R_Mater_301':					'Bullerskydd-väg/Materialtyp(H)',
	'Barig_64':						'Bärighet/Bärighetsklass',
	'Barig_504':					'Bärighet/Bärighetsklass vinterperiod',
	'Namn_457':						'C-Cykelled/Namn',
	'C_Cykelled':					'C-Cykelled',
	'C_Rekommenderad_bilvag_for_c':	'C-Rekommenderad_bilväg for cykel',
	'F_Cirkulationsplats':			'Cirkulationsplats(F)',
	'B_Cirkulationsplats':			'Circulationsplats(B)',
	'Vagde_10379':					'Driftbidrag statligt/Vägdelsnr',
	'Vagnr_10370':					'Driftbidrag statligt/Vägnr',
	'drift_2':						'Driftområde/namn',
	'entre_380':					'Driftområde/entreprenör',
	'Driftvandplats_2':				'Driftvändplats',
	'LageF_83':						'Farthinder/Läge',
	'TypAv_82':						'Farthinder/Typ',
	'FPV_dagliga_personresor_2':	'FPV-Dagliga personresor',
	'FPV_godstransporter_2':		'FPV-Godstransporter',
	'FPV_kollektivtrafik_2':		'FPV-Kollektivtrafik',
	'FPV_langvaga_personresor_2':	'FPV-Långväga personresor',
	'FPV_k_309':					'Funktionellt prioriterat vägnät/FPV-klass',
	'Framk_161':					'Framkomlighet för vissa fordonskombinationer/Framkomlighetsklass',
	'Klass_181':					'Funktionell vägklass/Klass',
	'Farjeled':						'Färjeled',
	'Farje_139':					'Färjeled/Färjeledsnamn',
	'F_Forbjuden_fardriktning':		'Förbjuden färdriktning(F)',
	'B_Forbjuden_fardriktning':		'Förbjuden färdriktning(B)',
	'F_Forbud_mot_trafik':			'Förbud mot trafik(F)',
	'B_Forbud_mot_trafik':			'Förbud mot trafik(B)',
	'Namn_130':						'Gatunamn/Namn',
	'GCM_belyst_1':					'GCM-belyst',
	'Trafi_86':						'GCM-passage/Trafikanttyp',
	'Passa_85':						'GCM-passage/Passagetyp',
	'GCM_passage_1':				'GCM-passage',
	'L_Separ_500':					'GCM-separation/Separation(V)',
	'R_Separ_500':					'GCM-separation/Separation(H)',
	'GCM_t_502':					'GCM-vägtyp/GCM-typ',
	'L_Gagata':						'Gågata(V)',
	'R_Gagata':						'Gågata(H)',
	'L_Gangfartsomrade':			'Gångfartsområde(V)',
	'R_Gangfartsomrade':			'Gångfartsområde(H)',
	'F_Hogst_225':					'Hastighetsgräns/Högsta tillåtna hastighet(F)',
	'B_Hogst_225':					'Hastighetsgräns/Högsta tillåtna hastighet(B)',
	'Hallplats_2':					'Hållplats',
	'Hojdh_145':					'Höjdhinder upp till 4,5 m/Höjdhinderidentitet',
	'Hojdh_144':					'Höjdhinder upp till 4,5 m/Höjdhindertyp',
	'Fri_h_143':					'Höjdhinder upp till 4,5 m/Fri höjd',
	'F_Beskr_124':					'Inskränkningar för transport av farligt gods/Beskrivning(F)',
	'B_Beskr_124':					'Inskränkningar för transport av farligt gods/Beskrivning(B)',
	'Plank_92':						'Järnvägskorsning/Plankorsnings-Id',
	'Senas_107':					'Järnvägskorsning/Senast ändrad',
	'X_koo_105':					'Järnvägskorsning/X-koordinat',
	'Y_koo_106':					'Järnvägskorsning/Y-koordinat',
	'Konta_103':					'Järnvägskorsning/Kontaktledning',
	'Kort__104':					'Järnvägskorsning/Kort magasin',
	'Antal_96':						'Järnvägskorsning/Antal spår',
	'Jvg_b_93':						'Järnvägskorsning/Jvg-bandel',
	'Vagpr_98':						'Järnvägskorsning/Vägprofil tvär kurva',
	'Vagpr_99':						'Järnvägskorsning/Vägprofil brant lutning',
	'Vagsk_100':					'Järnvägskorsning/Vägskydd',
	'Porta_101':					'Järnvägskorsning/Portalhöjd',
	'Tagfl_102':					'Järnvägskorsning/Tågflöde',
	'Vagpr_97':						'Järnvägskorsning/Vägprofil farligt vägkrön',
	'Jvg_k_94':						'Järnvägskorsning/Jvg-kilometer',
	'Jvg_m_95':						'Järnvägskorsning/Jvg-meter',
	'Katastrofoverfart_2':			'Katastroföverfart',
	'F_Korfa_517':					'Kollektivkörfält/Körfält-Körbana(F)',
	'B_Korfa_517':					'Kollektivkörfält/Körfält-Körbana(B)',
	'Lever_292':					'Leveranskvalitet DoU 2017/Leveranskvalitetsklass DoU 2017',
	'Miljozon':						'Miljözon',
	'mittr_10':						'Mittremsa/bredd',
	'Motortrafikled':				'Motortrafikled',
	'Motorvag':						'Motorväg',
	'F_Omkorningsforbud':			'Omkörningsförbud(F)',
	'B_Omkorningsforbud':			'Omkörningsförbud(B)',
	'L_Rastficka_2':				'Rastficka(V)',
	'R_Rastficka_2':				'Rastficka(H)',
	'Huvud_117':					'Rastplats/Huvudman',
	'Rastp_118':					'Rastplats/Rastplatsnamn',
	'Antal_124':					'Rastplats/Antal markerade parkeringsplatser för buss',
	'Antal_123':					'Rastplats/Antal markerade parkeringsplatser för husbil',
	'Antal_121':					'Rastplats/Antal markerade parkeringsplatser för lastbil',
	'Antal_122':					'Rastplats/Antal markerade parkeringsplatser för lastbil+släp',
	'Antal_120':					'Rastplats/Antal markerade parkeringsplatser för personbil+släp',
	'Ovrig_125':					'Rastplats/Övrig parkeringsmöjlighet',
	'Lanka_127':					'Rastplats/Länkadress',
	'Resta_131':					'Rastplats/Restaurang',
	'Serve_132':					'Rastplats/Servering',
	'Hundr_133':					'Rastplats/Hundrastgård',
	'Rastplats':					'Rastplats',
	'Antal_119':					'Rastplats/Antal markerade parkeringsplatser för personbil',
	'Dusch_126':					'Rastplats/Duschmöjlighet',
	'Rekom_185':					'Rekommenderad väg för farligt gods/Rekommendation',
	'L_Raffe_396':					'Räffla/Räffeltyp(V)',
	'R_Raffe_396':					'Räffla/Räffeltyp(H)',
	'Slitl_152':					'Slitlager/Slitlagertyp',
	'F_Stigningsfalt':				'Stigningsfält(F)',
	'B_Stigningsfalt':				'Stigningsfält(B)',
	'Vagna_406':					'Strategiskt vägnät för tyngre transporter/Vägnät för tyngre transporter',
	'TEN_T_489':					'TEN-T Vägnät/TEN-T-Logisk-Länk-id',
	'TEN_T_488':					'TEN-T Vägnät/TEN-T-Länk-id',
	'Tillg_169':					'Tillgänglighet/Tillgänglighetsklass',
	'ADT_f_117':					'Trafik/ÅDT fordon',
	'ADT_l_115':					'Trafik/ÅDT lastbilar',
	'ADT_a_113':					'Trafik/ÅDT axelpar',
	'Matar_121':					'Trafik/Mätårsperiod',
	'Tattbebyggt_omrade':			'Tättbebyggt område',
	'Viltpassage_i_plan_2':			'Viltpassage i plan',
	'L_Uppsa_320':					'Viltstängsel/uppsättningsår(V)',
	'R_Uppsa_320':					'Viltstängsel/uppsättningsår(H)',
	'L_Vilts_319':					'Viltstängsel/viltstängselstyp(V)',
	'R_Vilts_319':					'Viltstängsel/viltstängselstyp(H)',
	'L_Viltuthopp_2':				'Viltuthopp(V)',
	'R_Viltuthopp_2':				'Viltuthopp(H)',
	'drift_50':						'Vinter2003/driftsklass',
	'L_VVIS':						'VVIS(V)',  # Weather stations
	'R_VVIS':						'VVIS(H)',
	'slitl_25':						'VV-Slitlager/typ',
	'Bredd_156':					'Vägbredd/Bredd',
	'Passe_73':						'Väghinder/Passerbar bredd',
	'Hinde_72':						'Väghinder/Hindertyp',
	'Vagha_7':						'Väghållare/Väghållarnamn',
	'Forva_9':						'Väghållare/Förvaltningsform',
	'Vagha_6':						'Väghållare/Väghållartyp',
	'Kateg_380':					'Vägkategori/Kategori',
	'VN_Europavag':					'Europaväg',
	'F_Vagnummer':					'Vägnummer(F)',
	'B_Vagnummer':					'Vägnummer(B)',
	'Europ_16':						'Vägnummer/Europaväg',
	'Huvud_13':						'Vägnummer/Huvudnummer',
	'Under_14':						'Vägnummer/Undernummer',
	'Lanst_15':						'Vägnummer/Länstillhörighet',
	'L_vagra_282':					'Vägräcke/vägräckstyp(V)',
	'R_vagra_282':					'Vägräcke/vägräckstyp(H)',
	'L_gemen_283':					'Vägräcke/gemensamt mitträcke(V)',
	'R_gemen_283':					'Vägräcke/gemensamt mitträcke(H)',
	'L_vagra_277':					'Vägräckesavslutning/vägräckesavslutningstyp(V)',
	'R_vagra_277':					'Vägräckesavslutning/vägräckesavslutningstyp(H)',
	'Vagtr_474':					'Vägtrafiknät/Nättyp',
	'korfa_52':						'Vägtyp/körfältsbeskrivning',
	'vagty_41':						'Vägtyp/typ',
	'Vandm_176':					'Vändmöjlighet/Vändmöjlighetsklass',
	'Overledningsplats_2':			'Överledningsplats',
	'Namns_133':					'Övrigt vägnamn/Namnsättande organisation',
	'Namn_132':						'Övrigt vägnamn/Namn',
	'Korfa_497':					'Antal körfält/Körfältsantal',
	'F_ATK_Matplats_117':			'ATK-Mätplats(F)',
	'B_ATK_Matplats_117':			'ATK-Mätplats(B)',
	'F_Hogst_24':					'Begränsad bruttovikt/Högsta tillåtna bruttovikt(F)',
	'B_Hogst_24':					'Begränsad bruttovikt/Högsta tillåtna bruttovikt(B)',
	'F_Avser_28':					'Begränsad bruttovikt/Avser även fordonståg(F)',
	'B_Avser_28':					'Begränsad bruttovikt/Avser även fordonståg(B)',
	'Hogst_36':						'Begränsad fordonsbredd/Högsta tillåtna fordonsbredd',
	'Hogst_46':						'Begränsad fordonslängd/Högsta tillåtna fordonslängd',
	'OBJECTID':						'',
	'ROUTE_ID':						'',
	'FROM_MEASURE':					'MEASURE_FROM',
	'TO_MEASURE':					'MEASURE_TO',
	'KOMMUNNR':						'',
	'Shape':						'',
	'Shape_Length':					''
}



# Output message

def message (line):

	sys.stdout.write (line)
	sys.stdout.flush()



# Extension of dict class which returns an empty string if element does not exist

class Properties(dict):
	def __missing__(self, key):
		return None



# Convert tags

def osm_tags (segment):

	prop = Properties(segment['properties'])

	tags = {}

	# 1. Tag nodes

	crossing = {
#		1: {}	# planskild passage överfart  -->  Should create bridge on both neighbour segments
#		2: {}	# planskild passage underfart
		3:	{},	# övergångsställe och/eller cykelpassage/cykelöverfart i plan
		4:	{'crossing': 'traffic_signals'}, # signalreglerat övergångsställe och/eller signalreglerad cykelpassage/cykelöverfart i plan
		5:	{}  # annan ordnad passage i plan
	}

	if prop['GCM-passage/Passagetyp'] in crossing:  # Foot/cycleway crossing highway
		tags['highway'] = "crossing"
		tags.update(crossing[ prop['GCM-passage/Passagetyp'] ])
		create_node(segment, tags, ["GCM-passage/Passagetyp", "GCM-passage/Trafikanttyp"])

	railway_crossing = {
		1: {'crossing:barrier': 'full'},	# Helbom
		2: {'crossing:barrier': 'half'},	# Halvbom	
		3: {'crossing:bell': 'yes', 'crossing:light': 'yes'},	# Ljus och ljudsignal
		4: {'crossing:light': 'yes'},		# Ljussignal
		5: {'crossing:bell': 'yes'},		# Ljudsignal
		6: {'crossing:saltire': 'yes'},		# Kryssmärke
		7: {'crossing': 'uncontrolled'}		# Utan skydd
	}

	if prop['Järnvägskorsning/Vägskydd'] in railway_crossing:  # Railway crossing
		if prop['Vägtrafiknät/Nättyp'] == 1:
			tags['railway'] = "level_crossing"
		else:
			tags['railway'] = "crossing"
		tags.update(railway_crossing[ prop['Järnvägskorsning/Vägskydd'] ])
		create_node(segment, tags, ["Järnvägskorsning/Vägskydd", "Vägtrafiknät/Nättyp"])

	traffic_calming = {
		1: 'choker',	# avsmalning till ett körfält
		2: 'hump',		# gupp (cirkulärt gupp eller gupp med ramp utan gcm-passage)
		3: 'chicane',	# sidoförskjutning - avsmalning
		4: 'island',	# sidoförskjutning - refug
		5: 'dip',		# väghåla
		6: 'cushion',	# vägkudde
		7: 'table',		# förhöjd genomgående gcm-passage
		8: 'table',		# förhöjd korsning
		9: 'yes'	 	# övrigt farthinder
	}

	if prop['Farthinder/Typ'] in traffic_calming:  # Speed humps and other traffic calming objects
		tags['traffic_calming'] = traffic_calming[ prop['Farthinder/Typ'] ]
		create_node(segment, tags, ["Farthinder/Typ"])

	barrier = {
		1: 'bollard',			# pollare
		2: 'swing_gate',		# eftergivlig grind
		3: 'cycle_barrier',		# ej öppningsbar grind eller cykelfålla
		4: 'lift_gate',			# låst grind eller bom
		5: 'jersey_barrier',	# betonghinder    block?
		6: 'bus_trap',			# spårviddshinder
		99: 'yes'				# övrigt
	}

	if prop['Väghinder/Hindertyp'] in barrier:  # Barriers
		tags['barrier'] = barrier[ prop['Väghinder/Hindertyp'] ]
		create_node(segment, tags, ["Väghinder/Hindertyp"])

	if prop['ATK-Mätplats(F)'] or prop['ATK-Mätplats(B)']:  # Speed camera (currently put on highway node)
		tags['highway'] = "speed_camera"

		if prop['ATK-Mätplats(F)'] and prop['Hastighetsgräns/Högsta tillåtna hastighet(F)']:
			tags['maxspeed'] = str(prop['Hastighetsgräns/Högsta tillåtna hastighet(F)'])
		elif prop['ATK-Mätplats(B)'] and prop['Hastighetsgräns/Högsta tillåtna hastighet(B)']:
			tags['maxspeed'] = str(prop['Hastighetsgräns/Högsta tillåtna hastighet(B)'])

		create_node(segment, tags, ["ATK-Mätplats(F)", "ATK-Mätplats(B)", \
				"Hastighetsgräns/Högsta tillåtna hastighet(F)", "Hastighetsgräns/Högsta tillåtna hastighet(B)"])

	if prop['Rastplats']:  # Rest area (currently put on highway node)
		tags['highway'] = "rest_area"
		tags['name'] = prop['Rastplats/Rastplatsnamn'].strip()

		if prop['Rastplats/Antal markerade parkeringsplatser för personbil']:
			tags['capacity'] = str(prop['Rastplats/Antal markerade parkeringsplatser för personbil'])
		if prop['Rastplats/Antal markerade parkeringsplatser för lastbil+släp']:
			tags['capacity:hgv'] = str(prop['Rastplats/Antal markerade parkeringsplatser för lastbil+släp'])

		create_node(segment, tags, ["RastPlats", "Rastplats/Rastplatsnamn", "Rastplats/Restaurang", \
				"Rastplats/Antal markerade parkeringsplatser för personbil", \
				"Rastplats/Antal markerade parkeringsplatser för lastbil+släp"])

	if prop['Rastficka(V)'] or prop['Rastficka(H)']:  # Parking along highway (currently put on highway node)
		tags['amenity'] = "parking"
		create_node(segment, tags, ["Rastficka(V)", "Rastficka(H)"])

	tags = {}  # Reset tags for segments


	# 2. Tag ferries

	if prop['Färjeled']:  # Ferry

		tags['route'] = "ferry"
		tags['foot'] = "yes"

		if prop['Vägtrafiknät/Nättyp'] == 1:
			tags['motor_vehicle'] = "yes"
		else:
			tags['motor_vehicle'] = "no"

		ferry = {
			1: 'trunk',  # E road
			2: 'trunk',   # National road
			3: 'primary',  # Primary county road
			4: 'secondary'  # Other county road
		}

		if prop['Vägkategori/Kategori'] in ferry:  # Road catagory
			tags['ferry'] = ferry[ prop['Vägkategori/Kategori'] ]

		if prop['Vägnummer/Huvudnummer']:  # Road number
			if prop['Vägkategori/Kategori'] == 1:  # E road
				tags['ref'] = "E " + str(prop['Vägnummer/Huvudnummer'])
			else:
				tags['ref'] = str(prop['Vägnummer/Huvudnummer'])
 
		if prop['Färjeled/Färjeledsnamn']:  # Ferry line name
			tags['name'] = prop['Färjeled/Färjeledsnamn'].strip()

		return tags


	# 3. Tag bridges and tunnels (common for vehicles and pedestrians)
	# If only a foot/cycleway is underneath a short bridge, then the foot/cycleway is tagged as tunnel and there is no bridge tag.
	# The bridges dict contains the results of initial analysis of bridges and tunnels.

	if prop['Bro och tunnel/Konstruktion'] in [1, 4] and \
			(not prop['Bro och tunnel/Identitet'] or bridges[ prop['Bro och tunnel/Identitet'] ]['tag'] == "bridge" or \
			prop['Shape_Length'] > bridge_margin):

		tags['bridge'] = "yes"
		if prop['Bro och tunnel/Identitet']:
			tags['layer'] = bridges[ prop['Bro och tunnel/Identitet'] ]['layer']
		else:
			tags['layer'] = "1"

	elif prop['Bro och tunnel/Konstruktion'] == 3 or prop['Bro och tunnel/Konstruktion'] == 2 and \
			(prop['Bro och tunnel/Identitet'] and bridges[ prop['Bro och tunnel/Identitet'] ]['tag'] == "tunnel" or \
			not prop['Bro och tunnel/Identitet'] and (prop['Vägtrafiknät/Nättyp'] != 1 or prop['Shape_Length'] > bridge_margin)):

		tags['tunnel'] = "yes"
		tags['layer'] = "-1"

	# 4. Tag cycleways/footways

	if prop['Vägtrafiknät/Nättyp'] in [2, 4]:  # 2: Cycleway, 4: footway

		cycleway = {
			1: {'highway': 'cycleway'},		# cykelbana
			2: {'highway': 'cycleway'},		# cykelfält
			3: {'highway': 'cycleway', 'cycleway': 'crossing', 'segregated': 'yes'},	# cykelöverfart i plan/cykelpassage
			4: {'highway': 'footway', 'footway': 'crossing'},	# övergångsställe
			5: {'highway': 'cycleway'},		# gatupassage utan utmärkning
			8: {'highway': 'cycleway'},		# koppling till annat
			9: {'highway': 'cycleway'},		# annan cykelbar förbindelse
			10: {'highway': 'footway'},		# annan ej cykelbar förbindelse
			11: {'highway': 'footway'},		# gångbana
			12: {'highway': 'footway', 'footway': 'sidewalk'},	# trottoar
			13: {'highway': 'cycleway'},	# fortsättning i nätet
			14: {'highway': 'footway', 'covered': 'yes'},	# passage genom byggnad
			15: {'highway': 'cycleway'},	# ramp
			16: {'highway': 'platform'},	# perrong
			17: {'highway': 'steps'},		# trappa
			18: {'highway': 'footway', 'conveying': 'yes'},	# rulltrappa
			19: {'highway': 'footway', 'conveying': 'yes'},	# rullande trottoar
			20: {'highway': 'elevator'},	# hiss
			21: {'highway': 'elevator'},	# snedbanehiss
			22: {'aerialway': 'cable_car'},	# linbana
			23: {'railway': 'furnicular'},	# bergbana
			24: {'highway': 'pedestrian'},	# torg
			25: {'highway': 'footway'},		# kaj
			26: {'highway': 'pedestrian'},	# öppen yta
			27: {'route': 'ferry', 'foot': 'yes', 'motor_vehicle': 'no'},	# färja
			28: {'highway': 'cycleway', 'cycleway': 'crossing', 'segregated': 'yes'},	# cykelpassage och övergångsställe
			29: {'highway': 'cycleway', 'foot': 'no'}	# cykelbana ej lämplig för gång
		}

		if prop['GCM-separation/Separation(V)'] and prop['GCM-separation/Separation(V)'] == 1 or \
				prop['GCM-separation/Separation(H)'] and prop['GCM-separation/Separation(H)'] == 1:  # Sidewalk
			tags['highway'] = "footway"
			tags['footway'] = "sidewalk"
		elif prop['GCM-vägtyp/GCM-typ'] in cycleway:
			tags.update( cycleway[ prop['GCM-vägtyp/GCM-typ'] ] )
		else:
			tags['highway'] = "cycleway"

		# Swap cycleway to footway if footway network
		if prop['Vägtrafiknät/Nättyp'] == 4 and 1and "highway" in tags and tags['highway'] == "cycleway":
			tags['highway'] = "footway"
			if "cycleway" in tags:
				tags['footway'] = tags['cycleway']
				del tags['cycleway']

		# Include street name only for pedestrian highway
		if prop['Gatunamn/Namn'] and "highway" in tags and tags['highway'] == "pedestrian":
			tags['name'] = prop['Gatunamn/Namn'].strip()

		if prop['GCM-belyst'] and "highway" in tags:  # Street light
			tags['lit'] = "yes"

		# Foot/cycleways only get name if marked as cycleway route
		if prop['C-Cykelled/Namn'] and "highway" in tags and tags['highway'] == "cycleway":
			tags['cycleway:name'] = prop['C-Cykelled/Namn'].strip()  # Cycleway route

		if "bridge" in tags:
			if prop['Övrigt vägnamn/Namn'] and "bron" in prop['Övrigt vägnamn/Namn']:  # Bridge name
				tags['bridge:name'] = prop['Övrigt vägnamn/Namn'].strip()
			if prop['Bro och tunnel/Namn']:  # Description (may include bridge/tunnel name)
				tags['description'] = prop['Bro och tunnel/Namn'].strip()

		return tags


	# 5. Tag highways for motor vehicles
	# Follows official Swedish categories as used by Trafikverket and Lantmäteriet.
	# Sweden OSM has very strange category definitions for national and county roads which requires manual editing.

	if prop['Vägkategori/Kategori'] == 1:  # E road
		tags['highway'] = "trunk"

	elif prop['Vägkategori/Kategori'] == 2:  # National road
		tags['highway'] = "trunk"

	elif prop['Vägkategori/Kategori'] == 3:
		tags['highway'] = "primary"  # Primary county road

	elif prop['Vägkategori/Kategori'] == 4:
		tags['highway'] = "secondary"  # Other county road (alternative - use Lever_292)

	else:
		if prop['Gågata(V)']:
			tags['highway'] = "pedestrian"  # Pedestrian street

		elif prop['Gangfartsområde(V)'] or prop['Gangfartsområde(H)']:  # Sign E9
			tags['highway'] = "living_street"

		elif prop['Funktionell vägklass/Klass'] and  prop['Funktionell vägklass/Klass'] < 6:  # Functional road class
			tags['highway'] = "tertiary"

		# Private roads are tagged as residential/uncalssified if they have a road number or if functional class is < 9.
		# Functional class 9 is tagged as service.

		elif prop['Väghållare/Väghållartyp'] == 3:  # Private road owner
			if prop['Funktionell vägklass/Klass'] and prop['Funktionell vägklass/Klass'] < 9 or prop['Driftbidrag statligt/Vägnr']: # Alternative: < 8
				if prop['Tättbebyggt område']:
					tags['highway'] = "residential"  # Residential for urban areas
				else:
					tags['highway'] = "unclassified"  # Unclassified for rural areas
			else:
				tags['highway'] = "service"  # Service tag for functional road class 9
		else:
			tags['highway'] = "residential"  # Municipality is owner, seems to exist mostly in urban areas

	# Motorway/motorroad

	if prop['Motorväg']:
		tags['highway'] = "motorway"

	elif prop['Motortrafikled']:
		tags['motoroad'] = "yes"

	# Highway links are recognized indirectly by looking for the presence of FPV (functional priority road network) and 
	# delivery class ("leveranskvalitetsklass") below 4. Roundabouts excluded.

	if tags['highway'] in ['motorway', 'trunk', 'primary'] and prop['Funktionellt prioriterat vägnät/FPV-klass'] is None and \
			prop['Leveranskvalitet DoU 2017/Leveranskvalitetsklass DoU 2017'] and \
			prop['Leveranskvalitet DoU 2017/Leveranskvalitetsklass DoU 2017'] < 4 and \
			prop['Cirkulationsplats(F)'] is None and prop['Circulationsplats(B)'] is None:
		tags['highway'] += "_link"

	# Check oneway, used for other tags later

	if prop['Forbjuden färdriktning(B)']:
		tags['oneway'] = "yes"
		oneway = "forward"
	elif prop['Forbjuden färdriktning(F)']:
		tags['oneway'] = "yes"  # "-1"
		oneway = "backward"
		reverse_segment(segment, False)  # Reverse way nodes
		if debug:
			segment['properties']['REVERSE'] = 'yes'  # debug
	else:
		oneway = ""

	# Highway ref

	county_refs = {
		1:  'AB', # Stockholms län
		3:  'C',  # Uppsala län
		4:  'D',  # Södermanlands län
		5:  'E',  # Östergötlands län
		6:  'F',  # Jönköpings län
		7:  'G',  # Kronobergs län
		8:  'H',  # Kalmar län
		9:  'I',  # Gotlands län
		10: 'K',  # Blekinge län
		11: 'L',  # (f.d. Kristianstads län)
		12: 'M',  # Skåne län (f.d. Malmöhus län)
		13: 'N',  # Hallands län
		14: 'O',  # Västra Götalands län (f.d. Götebors- och Bohus län)
		15: 'P',  # (f.d. Älvsborgs län)
		16: 'R',  # (f.d. Skaraborgs län)
		17: 'S',  # Värmlands län
		18: 'T',  # Örebro län
		19: 'U',  # Västmanlands län
		20: 'W',  # Dalarnas län (f.d. Kopparbergs län)
		21: 'X',  # Gävleborgs län
		22: 'Y',  # Västernorrlands län
		23: 'Z',  # Jämtlands län
		24: 'AC', # Västerbottens län
		25: 'BD'  # Norrbottens län
	}

	if prop['Vägkategori/Kategori'] == 1:  # E road
		tags['ref'] = "E " + str(prop['Vägnummer/Huvudnummer'])
	elif prop['Vägkategori/Kategori'] in [2, 3]:  # Trunk and primary
		tags['ref'] = str(prop['Vägnummer/Huvudnummer'])
	elif prop['Vägkategori/Kategori'] == 4:  # Secondary
		tags['ref'] = county_refs[ prop['KOMMUNNR'] // 100 ] + " " + str(prop['Vägnummer/Huvudnummer'])  # Include county letter

	# Backward/forward tags

	tag_direction(tags, "junction", "roundabout", prop['Cirkulationsplats(F)'], prop['Circulationsplats(B)'], oneway)  # Roundabout

	tag_direction(tags, "maxspeed", None, prop['Hastighetsgräns/Högsta tillåtna hastighet(F)'], \
		prop['Hastighetsgräns/Högsta tillåtna hastighet(B)'], oneway)  # Maxspeed (exclude on service roads?, not signed?)

#	tag_direction(tags, "motor_vehicle", "no", prop['Forbud mot trafik(F)'], prop['Forbud mot trafik(B)'], oneway)  # Access

	tag_direction(tags, "overtaking", "no", prop['Omkörningsförbud(F)'], prop['Omkörningsförbud(F)'], oneway)  # Overtaking

	# Lanes

	if prop['Antal körfält/Körfältsantal'] and (prop['Antal körfält/Körfältsantal'] > 2 or \
			oneway and prop['Antal körfält/Körfältsantal'] > 1):
		tags['lanes'] = str(prop['Antal körfält/Körfältsantal'])  # Lanes

	tag_direction(tags, "psv", "yes", prop['Kollektivkörfält/Körfält-Körbana(F)']==2, \
		prop['Kollektivkörfält/Körfält-Körbana(B)']==2, oneway)  # PSV lanes

	tag_direction(tags, "motor_vehicle", "no", prop['Kollektivkörfält/Körfält-Körbana(F)']==2, \
		prop['Kollektivkörfält/Körfält-Körbana(B)']==2, oneway)  # PSV lanes

	tag_direction(tags, "lanes:psv", "1", prop['Kollektivkörfält/Körfält-Körbana(F)']==1, \
		prop['Kollektivkörfält/Körfält-Körbana(B)']==1, oneway)  # PSV lanes

	# Other highway tags

	if prop['Slitlager/Slitlagertyp'] == 1:  # Surface
		tags['surface'] = "paved"
	elif prop['Slitlager/Slitlagertyp'] == 2:
		tags['surface'] = "unpaved"

	if prop['Vägnummer/Huvudnummer']:  # Priority road
		tags['priority_road'] = "designated"

	if prop['C-Rekommenderad_bilväg for cykel']:  # Highway recommended for bikes
		tags['bicycle'] = "designated"

	# Names

	if prop['Gatunamn/Namn'] and not prop['Cirkulationsplats(F)'] and not prop['Circulationsplats(B)']:  # Street name
		tags['name'] = prop['Gatunamn/Namn'].strip()

	if prop['Övrigt vägnamn/Namn']:  # Bridge/tunnel name
		if "tunnel" in tags and "tunneln" in prop['Övrigt vägnamn/Namn']:
			tags['tunnel:name'] = prop['Övrigt vägnamn/Namn'].strip()
		elif "bridge" in tags and "bron" in prop['Övrigt vägnamn/Namn']:
			tags['bridge:name'] = prop['Övrigt vägnamn/Namn'].strip()

	if prop['Bro och tunnel/Namn'] and ("bridge" in tags or "tunnel" in tags):  # Description (may include bridge/tunnel name)
		tags['description'] = prop['Bro och tunnel/Namn'].strip()

	# Restrictions

#	if prop['Framkomlighet för vissa fordonskombinationer/Framkomlighetsklass'] == 4:  # Truck restrictions on forest roads
#		tags['hgv'] = "no"

	if prop['Höjdhinder upp till 4,5 m/Fri höjd']:
		tags['maxheight'] = str(prop['Höjdhinder upp till 4,5 m/Fri höjd'])  # Maxh height

	if prop['Begränsad fordonslängd/Högsta tillåtna fordonslängd']:
		tags['maxlength'] = str(prop['Begränsad fordonslängd/Högsta tillåtna fordonslängd'])  # Max length

	if prop['Begränsat axel-boggitryck/Högsta tillåtna tryck']:
		tags['maxaxleload'] = str(prop['Begränsat axel-boggitryck/Högsta tillåtna tryck'])  # Max legal load weight per axle

	maxweight = {
		1: "64.0",	# BK1
		2: "51.4",	# Bk2
		3: "37.5",	# BK3
		4: "74.0",	# BK4
		5: "74.0"	# BK4 särskilda vilkor
	}

	if prop['Bärighet/Bärighetsklass'] and "bridge" in tags:
		tags['maxweight'] = maxweight[ prop['Bärighet/Bärighetsklass'] ]  # Max total weight (only tagged on bridges)

	return tags



# Add tagged node to list of nodes
# Use coordinate from short way segment

def create_node (way, tags, nvdb_properties):

	node = {
		'type': 'feature',
		'properties': {}, 
		'tags': copy.deepcopy(tags),
		'geometry': {
			'type': 'Point',
			'coordinates': copy.deepcopy(way['geometry']['coordinates'][0][0])  # First coordinate of line
		}
	}

	for prop in nvdb_properties:
		if prop in way['properties']:
			node['properties'][ prop ] = copy.deepcopy(way['properties'][ prop ])

	nodes.append(node)



# Tag way with different forward and backward direction
# Adjust for possible oneway direction
# Paramters:
# - tags: will be update
# - tag: tag key to be used
# - value: if set, this is the tag value to be used
# - prop_forward/backward: if 1, use tag value paramter
# - oneway: direction of onway road (forward, backward), if any


def tag_direction (tags, tag, value, prop_forward, prop_backward, oneway):

	if prop_forward or prop_backward:

		if value and prop_forward == 1:
			prop_forward = value
		if value and prop_backward == 1:
			prop_backward = value

		if prop_forward == prop_backward:
			tags[ tag ] = str(prop_forward)  # Same tag for both directions, so no forwrd/backward suffix needed
		else:
			if prop_forward and oneway != "backward":
				if oneway == "forward":
					tags[ tag ] = str(prop_forward)  # Forward suffix not needed on oneway street
				else:
					tags[ tag + ":forward" ] = str(prop_forward)
			if prop_backward and oneway != "forward":
				if oneway == "backward":
					tags[ tag ] = str(prop_backward)  # Backward suffix not needed on oneway street  
				else:
					tags[ tag + ":backward" ] = str(prop_backward) 



# Tag segments and nodes in road network

def tag_network():

	message ("Converting tags ... ")

	global bridges  #, network

	for segment in segments['features']:
		segment['tags'] = {}

	# First build bridge/tunnel dict for the named structures

	bridges = {}
	bridge_segments = []

	for segment in segments['features']:
		prop = segment['properties']

		if "Bro och tunnel/Identitet" in prop:  # Unique id of structure
			bridge_id = prop['Bro och tunnel/Identitet']

			if bridge_id not in bridges:
				bridges[ bridge_id ] = {
					'car': 0,  # Will contain number of car highways underneath bridge
					'cycle': 0,  # Will contain number of foot/cycleways underneath bridge
					'length': 0,  # Length of bridge
					'layer': "1"  # Which layer to use
				}

			if prop['Bro och tunnel/Konstruktion'] in [2,3,4]:  # Current segment is under bridge
				if prop['Vägtrafiknät/Nättyp'] == 1 and prop['Bro och tunnel/Konstruktion'] != 3:
					bridges[ bridge_id ]['car'] += 1  # Highway is for cars
				else:
					bridges[ bridge_id ]['cycle'] += 1  # Foot/cycleways

			if prop['Bro och tunnel/Konstruktion'] == 1:  # Current segment is over bridge
				bridges[ bridge_id ]['length'] = max( bridges[ bridge_id ]['length'], prop['Shape_Length'] )
			elif prop['Bro och tunnel/Konstruktion'] == 4:  # Middel layer bridge
				bridges[ bridge_id ]['layer'] = "2"

		if "Bro och tunnel/Konstruktion" in prop:  # Build list of bridge segments for next iteration 
			bridge_segments.append(segment)


	# Discover missing bridge segments (without any bridge id) for the named structures and update

	# Loop all identified bridge segments (over and under)
	for segment1 in bridge_segments:
		prop1 = segment1['properties']
		if "Bro och tunnel/Identitet" not in prop1 and prop1['Bro och tunnel/Konstruktion'] in [2,3,4]:  # Under bridge, segment without structure

			# Then try to find intersecting highways over, i.e. a bridge
			for segment2 in bridge_segments:
				prop2 = segment2['properties']
				if debug:
					segment1['tags']['intersects'] = str(prop1['Bro och tunnel/Konstruktion'])
					segment2['tags']['intersects'] = str(prop2['Bro och tunnel/Konstruktion'])

				if prop2['Bro och tunnel/Konstruktion'] == 1 and segment1 != segment2 and intersects(segment1, segment2):  # Intersecting bridge found

					if "Bro och tunnel/Identitet" in prop2:  # Over bridge, segment with structure
						if prop1['Vägtrafiknät/Nättyp'] == 1 and prop1['Bro och tunnel/Konstruktion'] != 3:
							bridges[ prop2['Bro och tunnel/Identitet'] ]['car'] += 1
						else:
							bridges[ prop2['Bro och tunnel/Identitet'] ]['cycle'] += 1
					elif debug:
						segment1['tags']['intersection'] = "yes"

	# Tag according to highways over/under structure

	for bridge_id, bridge in bridges.items():
		if bridge['car'] > 0 or bridge['length'] > bridge_margin:
			bridges[ bridge_id ]['tag'] = "bridge"  # Always tag bridge if highway underneath is for cars
		elif bridge['cycle'] > 0:
			bridges[ bridge_id ]['tag'] = "tunnel"  # Tag tunnel underneath instead of bridge on top if only foot/cycleway underneath
		else:
			bridges[ bridge_id ]['tag'] = "bridge"  # Catch all

	message ("%i bridge/tunnel structures " % len(bridges))

	# Loop all features and tag

	for segment in segments['features']:
		segment['tags'].update(osm_tags(segment))

	message ("%i tagged nodes\n" % len(nodes))



# Identify intersecting segments
# Assumes line segments are stored in the format [(x0,y0),(x1,y1)]

def intersects (s0, s1):

	dx0 = s0['end_node'][0] - s0['start_node'][0]
	dx1 = s1['end_node'][0] - s1['start_node'][0]
	dy0 = s0['end_node'][1] - s0['start_node'][1]
	dy1 = s1['end_node'][1] - s1['start_node'][1]

	p0 = dy1 * (s1['end_node'][0] - s0['start_node'][0]) - dx1 * (s1['end_node'][1] - s0['start_node'][1])
	p1 = dy1 * (s1['end_node'][0] - s0['end_node'][0]) - dx1 * (s1['end_node'][1] - s0['end_node'][1])
	p2 = dy0 * (s0['end_node'][0] - s1['start_node'][0]) - dx0 * (s0['end_node'][1] - s1['start_node'][1])
	p3 = dy0 * (s0['end_node'][0] - s1['end_node'][0]) - dx0 * (s0['end_node'][1] - s1['end_node'][1])

	return (p0 * p1 <= 0) and (p2 * p3 <= 0)



# Return bearing in degrees of line between two points (longitude, latitude)

def compute_bearing (point1, point2):

	lon1, lat1, lon2, lat2 = map(math.radians, [point1[0], point1[1], point2[0], point2[1]])
	dLon = lon2 - lon1
	y = math.sin(dLon) * math.cos(lat2)
	x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
	angle = (math.degrees(math.atan2(y, x)) + 360) % 360
	return angle



# Compute change in bearing at intersection between two segments
# Used to determine if way should be split at intersection

def compute_junction_angle (segment1, segment2):

	line1 = segment1['geometry']['coordinates'][0]
	line2 = segment2['geometry']['coordinates'][0]

	if segment1['end_node'] == segment2['start_node']:
		angle1 = compute_bearing(line1[-2], line1[-1])
		angle2 = compute_bearing(line2[0], line2[1])
	elif segment1['start_node'] == segment2['end_node']:
		angle1 = compute_bearing(line1[1], line1[0])
		angle2 = compute_bearing(line2[-1], line2[-2])
	elif segment1['start_node'] == segment2['start_node']:
		angle1 = compute_bearing(line1[1], line1[0])
		angle2 = compute_bearing(line2[0], line2[1])
	else:  # elif segment1['end_node'] == segment2['end_node']:
		angle1 = compute_bearing(line1[-2], line1[-1])
		angle2 = compute_bearing(line2[-1], line2[-2])

	delta_angle = (angle2 - angle1 + 360) % 360

	if delta_angle > 180:
		delta_angle = delta_angle - 360

	return delta_angle



# Compute closest distance from point p3 to line segment [s1, s2].
# Works for short distances.

def line_distance(s1, s2, p3):

	x1, y1, x2, y2, x3, y3 = map(math.radians, [s1[0], s1[1], s2[0], s2[1], p3[0], p3[1]])

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



# Simplify polygon, i.e. reduce nodes within epsilon distance.
# Ramer-Douglas-Peucker method: https://en.wikipedia.org/wiki/Ramer–Douglas–Peucker_algorithm

def simplify_polygon(polygon, epsilon):

	dmax = 0.0
	index = 0
	for i in range(1, len(polygon) - 1):
		d = line_distance(polygon[0], polygon[-1], polygon[i])
		if d > dmax:
			index = i
			dmax = d

	if dmax >= epsilon:
		new_polygon = simplify_polygon(polygon[:index+1], epsilon)[:-1] + simplify_polygon(polygon[index:], epsilon)
	else:
		new_polygon = [polygon[0], polygon[-1]]

	return new_polygon



# Travel recursively in highway network to identify longest connected segments with identical tags.
# Will build long ways, however with no logical grouping beyond the highway tags.
# Paramters:
# - segment: To be tested for inclusion
# - node: Next node for traversion
# - test_way: Connected segments so far, including segment (should be avoided)
# - test_junctions: Junctions traversed so far, including node (should be avoided)
# - remaining_segments: Segments available for testing, excluding segments in test_way
# Returns longest connected way:
# - Legnth of that way
# - List of included segments, in sequence
# - List of junctions passed

def connected_way(segment, node, test_way, test_junctions, remaining_segments):

	if node == segment['start_node']:
		next_node = segment['end_node']
	else:
		next_node = segment['start_node']

	if segment['start_node'] == segment['end_node'] or next_node in test_junctions:  # Loop
		return (segment['properties']['Shape_Length'], [ segment ], [])

	# Iterate connected ways at junction

	best_length = 0
	best_sequence = []
	best_junctions = []

	# Check segments starting from next junction node
	for test_segment in junctions[ next_node ]['segments']:
		# New segment must not already have been used, must be available, must have the same tags, and oneways must have the same direction
		if test_segment not in test_way and test_segment in remaining_segments and test_segment['tags'] == segment['tags'] and \
			not ("oneway" in segment and "oneway" in test_segment and \
				segment['end_node'] != test_segment['start_node'] and segment['start_node'] != test_segment['end_node']):

			angle = compute_junction_angle(segment, test_segment)

			if abs(angle) < angle_margin:  # Avoid sharp angels
				length, sequence, used_junctions = connected_way(test_segment, next_node, test_way + [test_segment], test_junctions + [next_node], remaining_segments)

				if length > best_length:  # Keep best segment
					best_length = length
					best_sequence = sequence
					best_junctions = used_junctions

	total_length = segment['properties']['Shape_Length'] + best_length
	total_sequence = [ segment ] + best_sequence
	total_junctions = test_junctions + [next_node]

	return (total_length, total_sequence, total_junctions)



# Reverse direction of segment
# Swap direction tags (forward/backward) if selected and if present

def reverse_segment(segment, swap_tags):

	segment['start_node'], segment['end_node'] = segment['end_node'], segment['start_node']
	segment['geometry']['coordinates'][0].reverse()

	if swap_tags:
		new_tags = {}
		for tag in segment['tags']:

			if ":forward" in tag:
				new_tags[ tag.replace(":forward", ":backward") ] = segment['tags'][tag]
			elif ":backward" in tag:
				new_tags[ tag.replace(":backward", ":forward") ] = segment['tags'][tag]
			else:
				new_tags[tag] = segment['tags'][tag]

		segment['tags'] = new_tags



# Sinmplify highway network, i.e. create sequences of longer ways, using recursive method.
# The road network is traversed, testing all available branches to find the longest way with identical tags.
# Groups contain list of segments to be handled separately, i.e. not mixed in a connected way.
# Acceptable performance (depending on grouping).
# Parameter:
# - groups: Predefined list of segments to be handled separately, i.e. not mixed in a way.  

def simplify_network_recursive(groups):

	count = len(segments['features'])

	for group in groups.values():
		remaining_segments = group

		# Reapeat building sequences of longer ways until all segments have been used
		while remaining_segments:
			segment = remaining_segments[0]

			# First build sequence forward
			length_forward, sequence_forward, used_junctions = connected_way(segment, segment['start_node'], [ segment ], [], remaining_segments)
			if not sequence_forward:
				sys.exit ("Error - empty sequence forward\n")

			# Then try to building connecgted sequence backward
			length_backward, sequence_backward, used_junctions = connected_way(segment, segment['end_node'], sequence_forward, used_junctions, remaining_segments)
			if not sequence_backward:
				sys.exit ("Error - empty sequence backward\n")

			# Add the two
			sequence_backward.reverse()
			sequence = sequence_backward + sequence_forward[1:]

			# Add to collection of (longer) ways. May be only one segment if no match found
			ways.append(sequence)
			for segment in sequence:
				if segment not in remaining_segments:
					message ("Double: %s\n" % str(sequence))
				remaining_segments.remove(segment)

			message ("\r%i " % count)
			count -= len(sequence)

	# Check if any segments in a sequence needs to be reversed to get all segments in sequence in the same direction

	for way in ways:
		if len(way) > 1:
			last_segment = None
			for segment in way:
				if last_segment:
					if last_segment['end_node'] == segment['end_node'] or last_segment['start_node'] == segment['start_node']:
						reverse_segment(segment, True)
				last_segment = segment

			if way[0]['end_node'] != way[1]['start_node']:
				way.reverse()



# Alternative algorithm for identifying connected segments, from Norwegian nvdb2osm.
# Linear approach in which the next available segment is added as long as it has is connected and has identical tags.
# Very quick method.
# Parameter:
# - groups: Predefined list of segments to be handled separately, i.e. not to be mixed in a way.

def simplify_network_linear(groups):

	# Build connected ways within each group

	count = len(groups)

	for group_id, group_segments in iter(groups.items()):

		message ("\r%i " % count)
		count -= 1

		remaining_segments = copy.deepcopy(group_segments)

		# Repeat building sequences of longer ways until all segments have been used

		while remaining_segments:

			segment = remaining_segments[0]
			way = [ remaining_segments[0] ]
			remaining_segments.pop(0)
			first_node = segment['start_node']
			last_node = segment['end_node']

			# Build way forward

			found = True
			while found:
				found = False
				for segment in remaining_segments[:]:
					if segment['start_node'] == last_node:
						angle = compute_junction_angle(way[-1], segment)
						if abs(angle) < angle_margin:
							last_node = segment['end_node']
							way.append(segment)
							remaining_segments.remove(segment)
							found = True
							break

			# Build way backward

			found = True
			while found:
				found = False
				for segment in remaining_segments[:]:
					if segment['end_node'] == first_node:
						angle = compute_junction_angle(segment, way[0])
						if abs(angle) < angle_margin:
							first_node = segment['start_node']
							way.insert(0, segment)
							remaining_segments.remove(segment)
							found = True
							break

			# Create new ways, each with identical segment tags

			new_way = []
			way_tags = {}

			if not way_tags:
				way_tags = way[0]['tags']

			for segment in way:
				if segment['tags'] == way_tags:
					new_way.append(segment)
				else:
					ways.append(new_way)
					new_way = [ segment ]
					way_tags = segment['tags']

			ways.append(new_way)



# Prepare for output
# Paramter option:
# - route: "Roud id" provided from NVDB (sequence of segments, but often quite short).
# - refname: Hash/grouping based on highway ref, street name and highway category. Linear method which adds next connected segment.
# - recursive: Same hash/grouping as refname, but recursively traverses road network to find longest way.

def simplify_network(option):

	message ("Simplify network ...\n")

	# Simplify segment polygons, i.e. remove redundant nodes

	if simplify_factor != 0:
		for segment in segments['features']:
			segment['geometry']['coordinates'][0] = simplify_polygon(segment['geometry']['coordinates'][0], simplify_factor)

	# Build network junction structure.
	# They are the only nodes wich are shared between ways, and the only nodes with tagging.

	for segment in segments['features']:

		if segment['start_node'] not in junctions:
			junctions[ segment['start_node'] ] = {
				'tags': {},
				'properties': {},
				'segments': [ segment ]  # Pointer
			}
		else:
			junctions[ segment['start_node'] ]['segments'].append(segment)

		if segment['end_node'] not in junctions:
			junctions[ segment['end_node'] ] = {
				'tags': {},
				'properties': {},
				'segments': [ segment ]  # Pointer
			}
		else:
			junctions[ segment['end_node'] ]['segments'].append(segment)

	# Copy tags and properties from nodes to junctions

	for node in nodes:
		coordinate = (node['geometry']['coordinates'][0], node['geometry']['coordinates'][1])  # tuple
		if coordinate in junctions:
			junctions[ coordinate ]['tags'].update(node['tags'])
			junctions[ coordinate ]['properties'].update(node['properties'])

	# Build groups of segments for output

	groups = {}
	for segment in segments['features']:
		group_id = ""

		if option == "route":  # 
			if "ROUTE_ID" in segment['properties']:
				group_id = segment['properties']['ROUTE_ID']
				segment['tags']['ROUTE'] = group_id

		elif option in ["refname", "recursive"]:
			if "ref" in segment['tags']:
				group_id += segment['tags']['ref']
			if "Driftbidrag statligt/Vägnr" in segment['properties']:  # Road number for countryside
				group_id += str(segment['properties']['Driftbidrag statligt/Vägnr'])
			if "name" in segment['tags']:
				group_id += segment['tags']['name']
			if "highway" in segment['tags']:
				group_id += segment['tags']['highway']

		if group_id not in groups:
			groups[ group_id ] = [ segment ]  # Pointer
		else:
			groups[ group_id ].append( segment )  # Pointer

	# Use selected method

	if option == "recursive":
		simplify_network_recursive(groups)
	elif option in ["route", "refname"]:
		simplify_network_linear(groups)
	else:  # Segment only output, no longer ways
		for segment in segments['features']:
			ways.append([segment])

	message ("\rSimplified into %i ways\n" % len(ways))



# Generate one osm tag for output

def tag_property (osm_element, tag_key, tag_value):

	tag_value = tag_value.strip()
	if tag_value:
		osm_element.append(ET.Element("tag", k=tag_key, v=tag_value))



# Output road network or objects to OSM file

def output_network(filename):

	message ("Saving file... ")

	osm_id = -1000
	count = 0

	osm_root = ET.Element("osm", version="0.6", generator="nvdb2osm_sweden", upload="false")

	# First ouput all start/end nodes, which may be used by several ways.
	# The node id is saved for later reference by ways.

	for node_coordinate, node in iter(junctions.items()):
		osm_id -= 1
		osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node_coordinate[1]), lon=str(node_coordinate[0]))
		osm_root.append(osm_node)
		for key, value in iter(node['tags'].items()):
			tag_property (osm_node, key, value)
		if segment_output:
			for key, value in iter(node['properties'].items()):
				tag_property (osm_node, "NVDB_" + key.replace(" ", "_").replace("-", "_").replace("(", "_").replace(")", ""), str(value))

		node['osmid'] = osm_id

	# Then output all connected ways

	for way_segments in ways:

		segment = way_segments[0]
		osm_id -= 1
		osm_way_id = osm_id
		count += 1
		osm_way = ET.Element("way", id=str(osm_id), action="modify")
		osm_root.append(osm_way)

		# All tags are identical for the connected segments

		for key, value in iter(segment['tags'].items()):
			tag_property (osm_way, key, value)
			if segment_output:
				for key, value in iter(segment['properties'].items()):
					tag_property (osm_way, "NVDB_" + key.replace(" ", "_").replace("-", "_").replace("(", "_").replace(")", ""), str(value))

		osm_way.append(ET.Element("nd", ref=str(junctions[ segment['start_node'] ]['osmid'])))
	
		# Loop all segments in connected way

		for segment in way_segments:
			segment['osmid'] = osm_way_id
			line_geometry = segment['geometry']['coordinates'][0][1:-1]

			# Output all nodes in way

			for node in line_geometry:
				osm_id -= 1
				osm_node = ET.Element("node", id=str(osm_id), action="modify", lat=str(node[1]), lon=str(node[0]))
				osm_root.append(osm_node)
				osm_way.append(ET.Element("nd", ref=str(osm_id)))

			osm_way.append(ET.Element("nd", ref=str(junctions[ segment['end_node'] ]['osmid'])))

	# Produce OSM/XML file

	if segment_output:
		filename = filename.replace(".geojson", "") + "_segment.osm"
	else:
		filename = filename.replace(".geojson", "") + ".osm"

	osm_tree = ET.ElementTree(osm_root)
	osm_tree.write(filename, encoding="utf-8", method="xml", xml_declaration=True)

	message ("\nSaved %i elements in file '%s'\n" % (count, filename))



# Load geosjon file and round coordinates
# File is ordered as "homogeniserad" format from Lastkajen and converted to geosjon in QGIS

def load_file(filename):

	global segments

	message ("Loading file '%s' ... " % filename)

	file = open(filename)
	segments = json.load(file)  # Store all tagged (high)ways
	file.close()

	for segment in segments['features']:

		# Remove empty properties and rename to more readable names

		for key in list(segment['properties']):
			if segment['properties'][key] is None:
				del segment['properties'][key]
			else:
				if key in nvdb_attributes:
					if nvdb_attributes[key]:
						segment['properties'][ nvdb_attributes[key] ] = segment['properties'].pop(key)
				else:
					message ("*** Attribute %s not recognised\n" % key)

		# Round coordinates and get start/end nodes

		for coordinate in segment['geometry']['coordinates'][0]:
			coordinate[0] = round(coordinate[0], coordinate_decimals)
			coordinate[1] = round(coordinate[1], coordinate_decimals)
			coordinate[2] = round(coordinate[2], coordinate_decimals)

		segment['start_node'] = (segment['geometry']['coordinates'][0][0][0], segment['geometry']['coordinates'][0][0][1])  # tuple
		segment['end_node'] = (segment['geometry']['coordinates'][0][-1][0], segment['geometry']['coordinates'][0][-1][1])  # tuple

	message ("%i highway segments\n" % len(segments['features']))



# Main program

if __name__ == '__main__':

	# Load all ways

	start_time = time.time()
	message ("\nConverting Swedish NVDB tags\n")
	
	if len(sys.argv) > 1:
		filename = sys.argv[1]
	else:
		sys.exit("No input filename provided\n")

	if "-segment" in sys.argv:
		segment_output = True
		simplify_method = "segment"

	segments = []	# To store all highway segments
	nodes = []		# To store all tagged nodes
	junctions = {}	# To store all junctions
	ways = []		# To store connected ways for output

	# Process network

	load_file(filename)
	tag_network()
	simplify_network(simplify_method)  # Options: recursive, route or refname

	output_network(filename)

	message ("Time: %i seconds (%i segments per second)\n\n" % ((time.time() - start_time), (len(segments['features']) / (time.time() - start_time))))
