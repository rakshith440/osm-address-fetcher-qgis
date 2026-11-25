# OSM Address Fetcher for QGIS

A QGIS plugin that downloads address features from OpenStreetMap for a selected polygon and creates an address point layer.

> Development status: Experimental. Address completeness depends on source coverage. The plugin does not guarantee that every building or premise has an address.

## Current features

- Select a polygon layer
- Process a selected polygon or all polygons
- Download explicit OpenStreetMap address points
- Include addresses mapped on buildings
- Remove duplicate addresses
- Create a combined full-address field
- Create a temporary layer or save to GeoPackage

## Current data source

The current release queries OpenStreetMap through the Overpass API.

Public Overpass endpoints are suitable for smaller, occasional requests. Large or complex polygons can take longer or time out because public servers may be heavily loaded.

## Planned global architecture

The project is being redesigned as a source-neutral global premise-data tool.

Planned providers:

1. Overture Maps for global addresses, buildings, transportation and places
2. OpenAddresses for authoritative open addresses and available parcels, buildings and centerlines
3. Locally cached OpenStreetMap extracts
4. Microsoft Global ML Building Footprints
5. Google Research Open Buildings in supported regions

Planned performance improvements:

- Bounding-box cloud queries followed by exact local clipping
- Cloud-native GeoParquet access
- DuckDB spatial processing
- Local tile caching
- Background processing with QgsTask
- Batched GeoPackage writing
- Address-to-building matching
- Coverage and attribution reports

## Requirements

- QGIS 3.x
- Internet access for online providers
- A polygon layer defining the study area

Check `metadata.txt` for the currently supported minimum QGIS version.

## Installation from source

1. Download or clone this repository.
2. Ensure the plugin directory is named `osm_address_fetcher`.
3. Copy the directory to the active QGIS profile plugin folder:

   `QGIS3/profiles/default/python/plugins/osm_address_fetcher`

4. Restart QGIS.
5. Open **Plugins > Manage and Install Plugins**.
6. Enable **OSM Address Fetcher**.

On Windows, the default profile location is commonly:

`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`

## Usage

1. Load or create a polygon layer.
2. Open **OSM Address Fetcher**.
3. Select the polygon layer.
4. Choose either the selected polygon or all polygons.
5. Select the required address options.
6. Choose temporary output or GeoPackage output.
7. Click **Download Addresses**.

## Data-quality limitations

An empty result does not necessarily mean that no buildings or premises exist. It can mean that OpenStreetMap does not contain explicit `addr:*` tags in the selected area.

The project distinguishes between:

- Explicit addresses
- Interpolated addresses
- Addressed buildings
- Unaddressed potential premises
- Records requiring field verification

## Privacy and security

Do not commit API keys, customer data, internal project layers or proprietary datasets.

Future API credentials must be stored outside the repository, preferably using QGIS Authentication Manager.

## Contributing

Issues and pull requests are welcome. When reporting a problem, include:

- QGIS version
- Operating system
- Plugin version
- Approximate area size
- Error traceback
- Whether the polygon is valid
- Whether the problem can be reproduced without confidential data

## License

A project license will be added after confirming the intended redistribution and contribution terms.

## Attribution

OpenStreetMap data is provided by OpenStreetMap contributors and is subject to the Open Database License.

Additional providers will retain their required source and license attribution.
