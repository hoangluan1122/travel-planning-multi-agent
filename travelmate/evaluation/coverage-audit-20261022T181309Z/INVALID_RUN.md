# Invalid diagnostic-harness run — not product failures

This run was interrupted. The audit HTTP wrapper decoded gzip before reconstructing
the response with its original Content-Encoding header, causing a second decode.
Consequently its source_error outcomes cannot be attributed to the Place Agent.
Do not include this run in product pass/fail statistics. Original evidence is retained.
The wrapper was corrected to capture raw encoded bytes; a new run will be recorded
in a different timestamped directory. No production agent code was changed.
