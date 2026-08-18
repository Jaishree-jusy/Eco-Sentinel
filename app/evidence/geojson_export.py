"""
GeoJSON Polygon export - Module 8.

Writes a single-feature GeoJSON for one alert's polygon, with the alert's
fields flattened into properties (nested dicts don't serialize cleanly
through Fiona/GDAL's GeoJSON writer).
"""

import geopandas as gpd


def export_alert_geojson(alert, geometry, crs, output_path):
    properties = {k: v for k, v in alert.items() if k != "location"}
    if "location" in alert:
        properties["latitude"] = alert["location"]["latitude"]
        properties["longitude"] = alert["location"]["longitude"]

    gdf = gpd.GeoDataFrame([properties], geometry=[geometry], crs=crs)
    gdf.to_file(output_path, driver="GeoJSON")
    return output_path
