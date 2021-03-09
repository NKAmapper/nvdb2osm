# nvdb2osm
Converts NVDB highway data to OSM file.

To replace [elveg2osm](https://github.com/gomyhr/elveg2osm). Supports v3 of NVDB (2020 onward) and more features/tags.

NVDB conversion for Sweden is [here](https://github.com/NKAmapper/nvdb2osm/blob/master/README_SWEDEN.md). 

### Usage
1. **nvdb2osm -vegnett "kommune"**
   - Produces OSM file with road network for a given municipality (name or 4 digit municipality code).
   - Example: `nvdb2osm -vegnett 4601`for the road network of Bergen.

2. **nvdb2osm -vegobjekt "vegobjektkode" ["kommune"]**
   - Produces OSM file with all road objects of a given [type](http://labs.vegdata.no/nvdb-datakatalog/) (name or 2-3 digit object code).
   - Optionally within a given municipality (4 digit municipality code), else for the entire country of Norway.
   - Example: `nvdb2osm -vegobjekt 103 0301` for all traffic calming/speed bumps in Oslo.

3. **nvdb2osm -vegref "vegreferanse"**
   - Produces OSM file with road network for given road reference code.
   - Example: `nvdb2osm -vegref RA3` for Rv3 under construction (A).
   - The reference code is found by clicking on a road in [vegkart.no v3](http://vegkart.no).

4. **nvdb2osm -vegurl "api url"**
   - Produces OSM file defined by given NVDB API URL from [vegkart.no v3](http://vegkart.no) or
   any other permitted API URL as described in the [NVDB API documentation](https://nvdbapiles-v3.atlas.vegvesen.no/dokumentasjon/).
   - `&srid=wgs84` automatically added to the API URL string.
   - Bounding box only supported for WGS84 coordinates, not UTM from [vegkart.no v3](http://vegkart.no) (you will need to remove it or convert to WGS84).
   - Please make sure that `inkluder=lokasjon,egenskaper,metadata,geometri,vegsegmenter` is included in the API URL string.
   - Example 1: `nvdb2osm -vegurl "https://nvdbapiles-v3.atlas.vegvesen.no/vegobjekter/532?segmentering=true&inkluder=lokasjon,egenskaper,metadata,geometri,vegsegmenter&egenskap=4567=7041"` for all construction road objects in Norway (NB: Less detailed than a road network).
   - Example 2: Swap `7041` with `12160` in example 1 to get cycleways under construction.
   - The API URL is found by following this procedure:
     - Searching for a feature in [vegkart.no v3](http://vegkart.no) (see vegkart [tutorial](https://www.vegdata.no/vegkart/brukerveiledning/) )
     - Click *"xx vegobjekter"*.
     - Copy the link behind *"API" below the list*.
     - Remove the bounding box in the copied link if any (or convert it to WGS84 coordinates).
   - You may want to test the API URL in your web-browser.

Optional arguments:

* `-date "dato"` - Only ouput highways with coordinates provided during given date, e.g. "2020-08" for August 2020, or "2020" for full year.
* `-debug` - Get detailed information from NVDB
* `-segmentert` - Get segmented road network, i.e. road segments are not combined into longer ways.
* `"filnavn.osm"` - Set output filename (must end with ".osm")

### Example OSM files

* Generated OSM files for a few municipalities in [this folder](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134).
* You may generate more files using Python 3. No external dependencies beyond standard Python.

### Supported features

* Roads will get tagging for the following features:
  - Highway, including linked on/off ramps.
  - Ref (2-3 digit county roads will get primary tagging, otherwise secondary).
  - One-way streets.
  - Roundabouts.
  - Turn:lanes (may need to be adjusted manually; enable "Lane and road attributes" style in JOSM).
  - PSV lanes.
  - Tunnels and bridges.
* The following additional road objects from NVDB at the way level are supported:
  - Motorways and motorroads.
  - Tertiary roads based on NVDB functional road class (maintained in NVDB only in a few municipalities, e.g. Oslo).
  - Street names.
  - Max speeds.
  - Max height.
  - Max weight, for bridges only.
  - Max length, for tertiary and higher road classes.
  - Surface (asphalt excluded).
  - No snowplowing (national and county roads only).
  - Access restrictions.
  - Tunnel names, descriptions and access restrictions for bicycle and pedestrians.
  - Bridge descriptions (may currently mix left/right sides).
* The following road objects at the node level are supported. They may need manual inspection to ensure a better position.
  - Motorway junctions (needs to be moved to the correct off-ramp junction).
  - Ferry terminals.
  - Pedestrian crossings.
  - Railway crossings.
  - Speed bumps (tables).
  - Traffic signals (may need more traffic signal nodes at the junction) .
  - Barriers.
  - Cattle grids.
  - Passing places.
  - Stop signs (few cases).
* Turn restrictions are supported (relations).

### Current limitations

* Road objects will currently not get tagging for info from *other* road objects, such as speed limit, name, barrier etc.
* For road objects, the OSM file will contain info tags for all object data attributes from NVDB in its original format, with only limited OSM tagging supported. You will need to convert the info tagging to proper OSM tagging. Referenced roads will get osm tagging automatically.
* Please observe that *road object* will only produce the centre line of the road, while *road network* will get all separate left/right ways, so you may want to use road network whenever possible.
* NVDB includes geometry for turn lanes. In OSM, however, turn lanes should be tagged as turn:lanes instead of as separate ways. The generated OSM files includes these extra ways, but without a highway tag, so that they may be manually conflated in JOSM. Some of these ways should be kept as separate ways in OSM whenever they are physically separated from the main road, typically for lanes turning to the right.
* The generated ways currently are sometimes self-intersecting. Run *simplify way* with a factor of 0.2 in JOSM to fix it. 
* Road object ways currently have duplicate nodes at some intersections. Duplicates may be discovered and fixed automatically with the JOSM validator.
* NVDB contains mistakes. You may report mistakes at [Fiksvegdata](https://fiksvegdata.opentns.org/). Rapid response.

### Changelog

* 1.1:
  - Highway output grouped by road reference number, which produces longer ways.
  - New optional command `-date` which only ouputs highways with coordinates from the given date(span)
* 1.0:
  - Code converted to Python 3. NVDB api now supports tunnels and bridges for segments.

### References

* [vegkart.no v3](http://vegkart.no) - Statens Vegvesen: vegkart.no (new v3 version).
* [NVDB data catalogue](https://labs.vegdata.no/nvdb-datakatalog/) - All road objects by code and name.
* [NVDB api documentation](https://nvdbapiles-v3.atlas.vegvesen.no/dokumentasjon/) - Description of API parameters.
* [Håndbok V830](https://www.vegvesen.no/_attachment/61505) - Statens Vegvesen: Nasjonalt vegreferansesystem.
* [Fiksvegdata](https://fiksvegdata.opentns.org/) - For reporting mistakes in NVDB.
* [highway_merge.py](https://github.com/osmno/highway_merge) - Python tool for merging NVDB files with existing highways in OSM.
* [Road import plan](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)) - OpenStreetMap import wiki
* [Road import progress](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)/Progress) - OpenStreetMap progress page for NVDB/Elveg import
* [Veileder Elveg-import](https://wiki.openstreetmap.org/wiki/No:Veileder_Elveg-import) - OpenSteetMap guide wiki for the import process
