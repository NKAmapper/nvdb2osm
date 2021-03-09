# nvdbswe2osm

### Usage

1. Order the relevant municipality data from [Lastkajen](https://lastkajen.trafikverket.se/) at Trafikverket.
   * You need to register first (it is free).
   * Choose the _Homogeniserad_ format.
   * Choose the municipality.
   * Check for all attributes.
   * Download the GeoDB folder when it is ready (you get a mail).

2. Convert to geojson format.
   * Open the GeoDB folder in QGIS and export it to geosjon file.
   * Alternatively, convert using [ogr2ogr](https://gdal.org/programs/ogr2ogr.html) or similar tools.

3. Run program:

   <code>python3 nvdbswe2osm.py \<municipality.geojson\> [-segment]</code>

   * This will produce an .osm file.
   * The <code>-segment</code> option includes all NVDB attributes and does not combine segments into longer ways.

### Notes

* The current implementation is for testing.
* Some NVDB attributes are currently not supported, for example not all access restrictions are supported.
* Highways are combined into longer ways. There are three different algorithms to choose from in the program.
* Highways are split at sharp turns.
* Way polygons are simplified with a factor of 0.20 meters.
* Most municipalities are generated in a few seconds. The largest municipalities in Sweden run in a couple of minutes.
