-- One row per run, newest first: how far it got and how it ended.
SELECT
  run_id,
  ANY_VALUE(pipeline) AS pipeline,
  ANY_VALUE(trigger) AS trigger,
  ANY_VALUE(host) AS host,
  ANY_VALUE(commit_url) AS commit_url,
  ANY_VALUE(github_run_url) AS github_run_url,
  ANY_VALUE(cloud_run_execution) AS cloud_run_execution,
  MIN(started_at) AS started_at,
  MAX(finished_at) AS finished_at,
  COUNT(*) AS stages_run,
  COUNTIF(status = 'failed') AS stages_failed,
  COUNTIF(status = 'running') AS stages_running,
  CASE
    WHEN COUNTIF(status = 'failed') > 0 THEN 'failed'
    WHEN COUNTIF(status = 'running') > 0 THEN 'running'
    ELSE 'succeeded'
  END AS status,
  STRING_AGG(IF(status = 'failed', stage_name, NULL), ', ') AS failed_stage
FROM `${stage_runs_latest}`
GROUP BY run_id
