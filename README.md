# nvdb2osm
Converts NVDB highway data to OSM

### Usage
1. **nvdb2osm -vo "vegobjektkode" [-k "kommune"] > outfile.osm**
   - Produces osm file with all road objects of a given type
   - Optionally within a given municipality (4 digit municipality code), else for the entire country
   - Example: `nvdb2osm -vo 103 -k 0301` for all traffic calming/speed bumps in Oslo
  
2. **nvdb2osm -vn -k "kommune" > outfile.osm**
   - Produces osm file with road network for a given municipality (4 digit municipality code)
   - Example: `nvdb2osm -vn -k 1301`for road network of Bergen
  
3. **nvdb2osm -vr "vegreferanse" > outfile.osm**
   - Produces osm file with road network for given road reference code
   - Example: `nvdb2osm -vr 0400Ea6 >outfile.osm` for E6 under construction (a) at Hedmark county (0400)
   - The reference code is found by clicking on a road in [vegkart.no](http://vegkart.no)
  
4. **nvdb2osm "api url" > outfile.osm**
   - Produces osm file defined by given NVDB api url from [vegkart.no](http://vegkart.no) or any other permitted api url as described in [NVDB api documentation](https://www.vegvesen.no/nvdb/apidokumentasjon/)
   - `&srid=wgs84` automatically added to the apri url string
   - Bounding box only supported for WGS84 coordinates, not UTM from vegkart.no (you will need to remove it or convert to WGS84)
   - Please make sure that `inkluder=lokasjon,egenskaper,metadata,geometri` is included in the api url string 
   - Example 1: `nvdb2osm "https://www.vegvesen.no/nvdb/api/v2/vegobjekter/532?segmentering=true&inkluder=lokasjon,egenskaper,metadata,geometri&egenskap=4567=7041" >outfile.osm` for all construction road objects in Norway (NB: less detailed than a road network)
   - Example 2: Swap `7041` with `12160` in example 1 to get cycleways under construction
   - The api url is found by following this procudure:
     - Searching for a feature in [vegkart.no](http://vegkart.no)
     - Click *"Legg til søk"*
     - Click the first link named *"xx treff xx meter"*
     - Copy the link behind *"api"*
     - Remove the bounding box in the copied link if any (or convert it to WGS84 coordinates)
   - You may want to test the api url in your browser

### Notes

* Roads will get tagging for: highway, ref, oneway, roundabout, lanes, turn:lanes, psv, tunnel, bridge.
* The road network will currently not get tagging for information from other road objects, such as speed limit, name, barrier etc.
* Highway link tags such as *trunk_link* are currently tagged with the main tag only, i.e. *trunk*.
* For road objects, the osm file will contain all data fields from NVDB in its original format. You will need to convert to proper osm tagging. Referenced roads will get osm tagging automatically.
* Please observe that *road object* will only produce the center line of the road, while *road network* will get all separate lanes, so you may want to use road network whenever possible.
* The generated ways currently are sometimes self-intersecting. Run *simplify way* with a factor of 0.2 in JOSM to fix it. 
* The ways also currently have duplicate nodes at their end points and at intersections. Duplicates may be discovered and fixed automatically with the JOSM validator.

### References

* [vegkart.no](http://vegkart.no) - Statens Vegvesen: vegkart.no
* [NVDB data catalogue](http://labs.vegdata.no/nvdb-datakatalog/) - All road objects by code and name
* [NVDB api documentation](https://www.vegvesen.no/nvdb/apidokumentasjon/) - Description of api parameters
* [Håndbok V830](https://www.vegvesen.no/_attachment/61505) - Statens Vegvesen: Nasjonalt vegreferansesystem
