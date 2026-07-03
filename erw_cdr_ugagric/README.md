1. Create Area of Intrest (AOI) vector map (notebook 01)
   - Upload the administrative boundaries of Uganda shapefile
   - Check the coordinate reference system and ensure or convert to WGS84
   - Extract districts in the corn (maize belt) ie ["Masindi", "Mubende", "Kibaale", "Kakumiro", "Kagadi", "Kyankwanzi", "Kiboga", "Kyenjojo"]
   - Merge the polyons to create a single dissolved polygon called ug_corn_belt.

2. Download landuse raster dataset (notebook 02)
   - From ESA website, down the raster showing the global landuse of 2021
   - Load the dataset
   - Clip it the area of interest
   - Return it to show only cropland landuse types
   - export that for usage in modeling, call it **ug_agric_21landuse**

3. Download soil and rainfall data (noteboon 03a and 03b respectively)
   - For soil dat use the database provided by the Food and Agricultural Organisation (FAO)
   - For rainfall, use the free data from CHIRPS accessed from S3 buckets

4. Run the SCEPTER model to determine the carbon reatained in tonnes (notebook 04)