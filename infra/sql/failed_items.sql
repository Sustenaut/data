-- What failed in each failed stage run, one row per failed item (or one row
-- for a stage that could not start): the first place to look.
SELECT
  s.run_id,
  s.stage_name,
  s.finished_at,
  s.commit_url,
  s.github_run_url,
  s.cloud_run_execution,
  JSON_VALUE(item, '$.item_key') AS item_key,
  COALESCE(JSON_VALUE(item, '$.error_class'), s.error_class) AS error_class,
  COALESCE(JSON_VALUE(item, '$.error_message'), s.error_message) AS error_message,
  COALESCE(JSON_VALUE(item, '$.traceback_tail'), s.traceback_tail) AS traceback_tail,
  JSON_VALUE(item, '$.input_key') AS input_key
FROM `${stage_runs_latest}` AS s
LEFT JOIN UNNEST(JSON_QUERY_ARRAY(s.items)) AS item
  ON JSON_VALUE(item, '$.status') = 'failed'
WHERE s.status = 'failed'
