-- Each stage of each run as it ended (its newest row), with where its code
-- and its trigger can be looked up.
SELECT
  run_id,
  pipeline,
  stage_index,
  stage_name,
  status,
  trigger,
  host,
  started_at,
  finished_at,
  TIMESTAMP_DIFF(finished_at, started_at, SECOND) AS seconds,
  parser_name,
  parser_version,
  parser_code_hash,
  code_version,
  IF(code_version = 'dev', NULL,
     CONCAT('https://github.com/Sustenaut/soldera/commit/', code_version)) AS commit_url,
  JSON_VALUE(trigger_context, '$.github_run_url') AS github_run_url,
  JSON_VALUE(trigger_context, '$.cloud_run_execution') AS cloud_run_execution,
  items_total,
  items_succeeded,
  items_cached,
  items_failed,
  rows_out,
  notes_count,
  error_class,
  error_message,
  traceback_tail,
  items,
  upstream_manifest_uri,
  output_manifest_uri,
  notes_uri
FROM `${table}`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY run_id, stage_name ORDER BY logged_at DESC) = 1
