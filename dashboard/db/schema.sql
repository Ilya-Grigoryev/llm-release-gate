-- One row per artifact of the gate action: what the gate decided on one run of one pull request.
create table if not exists runs (
  artifact_id    bigint primary key,
  repo_id        bigint not null,
  repo           text not null,              -- owner/name when the run was read
  gate           text not null default '',   -- the action's `name` input; '' for an unnamed gate
  run_id         bigint not null,            -- the workflow run
  attempt        int not null,
  pr             int,
  title          text,
  branch         text,
  sha            text,
  url            text,                       -- the workflow run on GitHub
  created_at     timestamptz not null,
  outcome        text not null,
  exit_code      int not null,
  base_mean      double precision,
  candidate_mean double precision,
  diff_pp        double precision,
  cost           double precision,
  same_version   boolean,
  verdict        jsonb,
  comment        text,
  base           jsonb not null,             -- the records the gate compared, one per case and repetition
  candidate      jsonb not null
);
create index if not exists runs_repo on runs (repo_id, created_at desc);
