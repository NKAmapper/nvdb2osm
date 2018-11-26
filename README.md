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
  
4. **nvdb2osm "http string from vegnett.no" > outfile.osm**
   - Produces osm file defined by given NVDB http api call from [vegkart.no](http://vegkart.no)
   - `&srid=wgs84` automatically added to the string
   - Bounding box only supported for WGS84 coordinates, not UTM from vegkart.no (you will need to remove it or convert to WGS84)
   - Please make sure that `inkluder=lokasjon,egenskaper,metadata,geometri` is included in the string 
   - Example: `nvdb2osm "https://www.vegvesen.no/nvdb/api/v2/vegobjekter/532?segmentering=true&inkluder=lokasjon,egenskaper,metadata,geometri&egenskap=4567=7041" >outfile.osm` for all construction road objects in Norway (NB: less detailed than a road network)
   - The api string is found by following this procudure:
     - Searching for a feature in [vegkart.no](http://vegkart.no)
     - Click *"Legg til søk"*
     - Click the first link named *"xx treff xx meter"*
     - Copy the link behind *"api"*
     - Remove the bounding box in the copied link if any (or convert it to WGS84 coordinates)
   - You may want to test the http string in your browser
   
### References

* [vegkart.no](http://vegkart.no) - Statens Vegvesen: vegkart.no
* [NVDB data catalogue](http://labs.vegdata.no/nvdb-datakatalog/) - All road objects by code and name
* [NVDB api documentation](https://www.vegvesen.no/nvdb/apidokumentasjon/) - Description of api parameters
* [Håndbok V830](https://www.vegvesen.no/_attachment/61505) - Statens Vegvesen: Nasjonalt vegreferansesystem
