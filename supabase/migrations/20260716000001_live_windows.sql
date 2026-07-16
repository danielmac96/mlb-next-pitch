-- Windowed live polling + go-live schedule changes.
--
-- The live poller now only fires during "game windows": from each game's
-- scheduled start until 4 hours after, extended while any board game is
-- still live (extra innings / delays). Outside all windows the cron tick
-- skips the edge-function call entirely, so the pipeline sleeps overnight.
--
-- Odds ingestion and settlement are paused until odds/records ship in the
-- UI; daily ingest moves to 13:00 UTC (9:00 AM ET during the season) so the
-- day's schedule — which defines the polling windows — loads each morning.

-- Unschedule: odds-ingest + settle stay off; daily-ingest and live-poll are
-- re-scheduled below with the new timing.
do $$
declare j record;
begin
    for j in select jobid, jobname from cron.job
        where jobname in ('np-odds-ingest','np-settle','np-daily-ingest','np-live-poll')
    loop
        perform cron.unschedule(j.jobid);
    end loop;
end $$;

-- Daily schedule load / full refresh at 13:00 UTC = 9:00 AM EDT.
select cron.schedule('np-daily-ingest', '0 13 * * *', $$select call_edge_function('daily-ingest')$$);

-- Live poller: every 30 seconds, but only inside a game window.
select cron.schedule('np-live-poll', '30 seconds', $$
do $body$
begin
    if exists (
        -- a game is inside its [start, start + 4h) window
        select 1 from games
        where start_ts <= now() and now() < start_ts + interval '4 hours'
    ) or exists (
        -- or a board game is still live: keeps polling past 4h while MLB
        -- says in-progress, and lets live-poll's stale-cleanup mark ended
        -- games final, which closes the window loop
        select 1 from live_state where status = 'live'
    ) then
        perform call_edge_function('live-poll');
    end if;
end $body$
$$);
