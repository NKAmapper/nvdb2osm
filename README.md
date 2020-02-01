# nvdb2osm
Converts NVDB highway data to OSM file.
Same as Elveg, but supporting more features/tags and supporting new municipality boundaries since 2020.

### Usage
1. **nvdb2osm -vegnett "kommune" > outfile.osm**
   - Produces osm file with road network for a given municipality (4 digit municipality code)
   - Example: `nvdb2osm -vegnett 1301`for road network of Bergen

2. **nvdb2osm -vegobjekt "vegobjektkode" ["kommune"]**
   - Produces osm file with all road objects of a given type
   - Optionally within a given municipality (4 digit municipality code), else for the entire country
   - Example: `nvdb2osm -vegobjekt 103 0301` for all traffic calming/speed bumps in Oslo

3. **nvdb2osm -vegref "vegreferanse"**
   - Produces osm file with road network for given road reference code
   - Example: `nvdb2osm -vegref RA3` for Rv3 under construction (A)
   - The reference code is found by clicking on a road in [vegkart.no](https://vegkart-v3.utv.atlas.vegvesen.no/) v3
  
4. **nvdb2osm -vegurl "api url"**
   - Produces osm file defined by given NVDB api url from [vegkart.no](https://vegkart-v3.utv.atlas.vegvesen.no/) v3 or any other permitted api url as described in [NVDB api documentation](https://nvdbapilesv3.docs.apiary.io/)
   - `&srid=wgs84` automatically added to the apri url string
   - Bounding box only supported for WGS84 coordinates, not UTM from [vegkart.no](https://vegkart-v3.utv.atlas.vegvesen.no/) v3 (you will need to remove it or convert to WGS84)
   - Please make sure that `inkluder=lokasjon,egenskaper,metadata,geometri,vegsegmenter` is included in the api url string 
   - Example 1: `nvdb2osm -vegurl "https://www.vegvesen.no/nvdb/api/v3/vegobjekter/532?segmentering=true&inkluder=lokasjon,egenskaper,metadata,geometri,vegsegmenter&egenskap=4567=7041"` for all construction road objects in Norway (NB: less detailed than a road network)
   - Example 2: Swap `7041` with `12160` in example 1 to get cycleways under construction
   - The api url is found by following this procudure:
     - Searching for a feature in [vegkart.no](https://vegkart-v3.utv.atlas.vegvesen.no/)
     - Click *"xx vegobjekter"*
     - Copy the link behind *"api" below the list*
     - Remove the bounding box in the copied link if any (or convert it to WGS84 coordinates)
   - You may want to test the api url in your browser

### Supported features

* Roads will get tagging for the following tagging:
  - Highway, including linked on/off ramps
  - Ref (2-3 digit county roads will get primary tagging, otherwise secondary)
  - Oneway streets
  - Roundabouts
  - Turn:lanes (may need manual adjustments)
  - PSV lanes
  - Tunnels and bridges (temporary fix due to NVDB api limitations)
* The following additional road objects from NVDB at the way level are supported:
  - Moroways and motorroads
  - Tertiary roads based on NVDB functional road class (maintained in NVDB only in a few municipalities, e.g. Oslo)
  - Street names
  - Max speeds
  - Surface (asphalt excluded)
  - Max height
  - No snowplowing (national and county roads only)
  - Access restrictions
  - Tunnel names, descriptions and access restrictions for bicycle and pedestrians
  - Bridge descriptions (may currently mix left/right sides)
* The following road objects at the node level are supported. They may need manual inspection to ensure a better position.
  - Motorway junctions (needs to be moved to the correct off-ramp junction)
  - Ferry terminals
  - Pedestrian crossings
  - Railway crossings
  - Speed bumps (tables)
  - Traffic lights
  - Barriers
  - Cattle grids
  - Passing places
  - Stop signs (few cases)
* Turn restrictions are supported (relations)

### Current limitations

* The road network will currently not get tagging for information from other road objects, such as speed limit, name, barrier etc.
* For road objects, the osm file will contain all data fields from NVDB in its original format. You will need to convert to proper osm tagging. Referenced roads will get osm tagging automatically.
* Please observe that *road object* will only produce the center line of the road, while *road network* will get all separate lanes, so you may want to use road network whenever possible.
* The generated ways currently are sometimes self-intersecting. Run *simplify way* with a factor of 0.2 in JOSM to fix it. 
* Road object ways currently have duplicate nodes at some intersections. Duplicates may be discovered and fixed automatically with the JOSM validator.
* NVDB contains mistakes. You may report mistakes at [Fiksvegdata](https://fiksvegdata.opentns.org/). Rapid response.

### References

* [vegkart.no](https://vegkart-v3.utv.atlas.vegvesen.no/) v3 - Statens Vegvesen: vegkart.no (new v3 test version)
* [NVDB data catalogue](http://labs.vegdata.no/nvdb-datakatalog/) - All road objects by code and name
* [NVDB api documentation](https://nvdbapilesv3.docs.apiary.io/) - Description of api parameters
* [Håndbok V830](https://www.vegvesen.no/_attachment/61505) - Statens Vegvesen: Nasjonalt vegreferansesystem
* [Fiksvegdata](https://fiksvegdata.opentns.org/) - For reporting mistakes in NVDB
