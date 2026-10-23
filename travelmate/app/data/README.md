# Reference region snapshots — not a POI database

vietnam_regions.json contains 34 province-level reference geometries from a pinned
vietnamese-provinces-database commit and 63 historical geometries from geoBoundaries.
It contains no hotels, restaurants, prices, images or generated search results.
POIs are retrieved from the network at request time, subject to the source cache.

The importer scripts/import_vietnam_boundaries.py pins URLs, records SHA-256 hashes
and acquisition date, and refuses to overwrite an existing snapshot. Geometry is
retained; fields are adapted into an internal schema. See sources in the JSON.

## Current reference set

Repository: https://github.com/thanglequoc/vietnamese-provinces-database
Commit: 8b78ba5118715e1fa81769286724db79346abf52
Resource: mongodb/gis/mongo_data_vn_province_gis.json (34 records)
Reference version: resource directory geojson_11Mar2026 (README reports fetch 13 March 2026).

Upstream states GIS derives from Bando.com.vn. Its GIS README explicitly requires
consulting Bando.com.vn terms for usage restrictions. The repository MIT software
license below must NOT be construed as independent, unrestricted licensing of GIS
source data. This snapshot is for local research/reference; review source terms
and rights before redistribution or production/commercial deployment.

MIT License

Copyright (c) 2021 Thang Le Quoc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Historical reference set

Provider: Government of Viet Nam / HDX via geoBoundaries gbHumanitarian.
Boundary version: 2020, 63 regions, simplified geometry. NOT current administrative divisions.
Pinned release: wmgeolab/geoBoundaries commit 9469f09.
Resource: releaseData/gbHumanitarian/VNM/ADM1/geoBoundaries-VNM-ADM1_simplified.geojson
Metadata: https://www.geoboundaries.org/api/current/gbHumanitarian/VNM/ADM1/
Original source: https://data.humdata.org/dataset/cod-ab-vnm
License reported by provider: CC BY 3.0 IGO.
License: https://creativecommons.org/licenses/by/3.0/igo/
Changes: schema adaptation only; geometric simplification was performed upstream.

Both sets are approximate reference boundaries, not legal/cadastral verification.
Retain attribution, version and historical status when displaying or exporting.
