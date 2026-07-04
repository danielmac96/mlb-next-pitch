-- Optional demo seed — a small, clearly-labeled dataset so the board and
-- track record render populated even when no MLB games are live (off-hours
-- investor demos). Everything here is source='demo' / model_version='demo'
-- so it is trivially distinguishable from real graded history and can be
-- removed with:  delete from picks where source='demo';
--                delete from live_state where game_pk >= 900000000;
--
-- Apply after migrations:  supabase db query < supabase/seed_demo.sql
-- Do NOT run this in a production instance you intend to show as a real
-- track record — it will inflate /record with fictional results.

-- A couple of "live" games so the board isn't empty.
insert into games (game_pk, official_date, season, status, home_team, away_team, home_abbr, away_abbr, venue_name, home_score, away_score)
values
  (900000001, current_date, extract(year from current_date)::int, 'In Progress', 'Boston Red Sox', 'New York Yankees', 'BOS', 'NYY', 'Fenway Park', 2, 1),
  (900000002, current_date, extract(year from current_date)::int, 'In Progress', 'San Francisco Giants', 'Los Angeles Dodgers', 'SF', 'LAD', 'Oracle Park', 0, 3)
on conflict (game_pk) do update set status = excluded.status,
  home_score = excluded.home_score, away_score = excluded.away_score;

insert into player_info (player_id, full_name, pitch_hand, bat_side) values
  (543037, 'Gerrit Cole', 'R', 'R'),
  (646240, 'Rafael Devers', null, 'L'),
  (592789, 'Logan Webb', 'R', 'R'),
  (605141, 'Mookie Betts', null, 'R')
on conflict (player_id) do nothing;

insert into live_state (game_pk, status, inning, top_inning, batter_id, pitcher_id, balls, strikes, outs, pitch_count_pa, last_pitch_ts, home_score, away_score, raw_json)
values
  (900000001, 'live', 5, true, 646240, 543037, 1, 2, 1, 4, now(), 2, 1,
   jsonb_build_object('away_team','New York Yankees','home_team','Boston Red Sox','away_abbr','NYY','home_abbr','BOS',
     'current_pa_pitches', jsonb_build_array(
       jsonb_build_object('pitch_number',1,'pitch_type','FF','start_speed',97.6,'zone',5,'description','called_strike','result_category','strike_foul','balls',0,'strikes',1),
       jsonb_build_object('pitch_number',2,'pitch_type','SL','start_speed',88.2,'zone',13,'description','ball','result_category','ball','balls',1,'strikes',1),
       jsonb_build_object('pitch_number',3,'pitch_type','FF','start_speed',98.0,'zone',6,'description','foul','result_category','strike_foul','balls',1,'strikes',2),
       jsonb_build_object('pitch_number',4,'pitch_type','KC','start_speed',84.5,'zone',14,'description','ball','result_category','ball','balls',1,'strikes',2)
     ))),
  (900000002, 'live', 3, false, 605141, 592789, 0, 0, 0, 1, now(), 0, 3,
   jsonb_build_object('away_team','Los Angeles Dodgers','home_team','San Francisco Giants','away_abbr','LAD','home_abbr','SF',
     'current_pa_pitches', jsonb_build_array(
       jsonb_build_object('pitch_number',1,'pitch_type','SI','start_speed',92.8,'zone',8,'description','ball','result_category','ball','balls',1,'strikes',0)
     )))
on conflict (game_pk) do update set updated_at = now(), raw_json = excluded.raw_json,
  batter_id = excluded.batter_id, pitcher_id = excluded.pitcher_id,
  balls = excluded.balls, strikes = excluded.strikes, pitch_count_pa = excluded.pitch_count_pa;

-- Live predictions for those games so the markets/edge columns populate.
insert into predictions (game_pk, at_bat_index, pitch_number, market, predicted_value, confidence, probs, recommendation, line, price, edge, model_version)
values
  (900000001, 12, 4, 'pitch_speed_ou', 96.8, 0.60, null, 'over', 95.5, -110, 0.076, 'demo'),
  (900000001, 12, 4, 'pitch_result', 0.49, 0.49, '{"strike_foul":0.49,"ball":0.31,"in_play":0.20}', 'strike_foul', null, null, null, 'demo'),
  (900000001, 12, 4, 'ab_result', 0.41, 0.41, '{"strikeout":0.41,"walk":0.09,"hit":0.20,"out":0.30}', 'strikeout', null, null, null, 'demo'),
  (900000001, 12, 4, 'ab_pitches_ou', 5.1, 0.57, null, 'over', 4.5, -105, 0.048, 'demo'),
  (900000002, 5, 1, 'pitch_speed_ou', 93.4, 0.55, null, 'over', 92.5, -115, 0.033, 'demo'),
  (900000002, 5, 1, 'ab_result', 0.33, 0.33, '{"strikeout":0.18,"walk":0.10,"hit":0.33,"out":0.39}', 'out', null, null, null, 'demo');

-- Today's published picks.
insert into picks (pick_date, game_pk, at_bat_index, market, recommendation, label, line, price, confidence, edge, units, book, source, model_version, status, payload)
values
  (current_date, 900000001, 12, 'ab_result', 'strikeout', 'Rafael Devers — Strikeout', null, -115, 0.64, 0.082, 1, 'draftkings', 'demo', 'demo', 'pending',
   jsonb_build_object('game', jsonb_build_object('away','NYY','home','BOS','matchup','NYY @ BOS','venue','Fenway Park'),
     'pitcher', jsonb_build_object('name','Gerrit Cole','hand','R'),
     'batter', jsonb_build_object('name','Rafael Devers','hand','L'),
     'bullets', jsonb_build_array('Cole is running a 33% K rate over his last 6 starts.','Devers strikes out 29% vs RHP.','Model 64% vs -115 implied 53.5% — +8.2% edge.'))),
  (current_date, 900000001, 12, 'pitch_speed_ou', 'over', 'Next Pitch Over 95.5', 95.5, -110, 0.60, 0.076, 1, 'fanduel', 'demo', 'demo', 'pending',
   jsonb_build_object('game', jsonb_build_object('away','NYY','home','BOS','matchup','NYY @ BOS')))
on conflict (pick_date, game_pk, market, at_bat_index, recommendation) do nothing;

-- A short graded history so /record is non-empty.
insert into picks (pick_date, game_pk, market, recommendation, label, price, units, source, model_version, status, profit_units, graded_at, payload)
values
  (current_date - 1, 899000001, 'ab_result', 'strikeout', 'Bobby Witt Jr. — Strikeout', 105, 1, 'demo', 'demo', 'win', 1.05, now(), jsonb_build_object('game', jsonb_build_object('matchup','KC @ MIN'))),
  (current_date - 1, 899000002, 'pitch_speed_ou', 'over', 'Next Pitch Over 95.5', -110, 1, 'demo', 'demo', 'win', 0.909, now(), jsonb_build_object('game', jsonb_build_object('matchup','MIA @ CHC'))),
  (current_date - 1, 899000003, 'ab_result', 'hit', 'Gunnar Henderson — Hit', 140, 1, 'demo', 'demo', 'loss', -1.0, now(), jsonb_build_object('game', jsonb_build_object('matchup','BAL @ TB'))),
  (current_date - 2, 899000004, 'ab_pitches_ou', 'under', 'Pitches in AB Under 4.5', -105, 1, 'demo', 'demo', 'win', 0.952, now(), jsonb_build_object('game', jsonb_build_object('matchup','STL @ MIL'))),
  (current_date - 2, 899000005, 'pitch_result', 'strike_foul', 'Next Pitch Strike or Foul', -125, 1, 'demo', 'demo', 'push', 0, now(), jsonb_build_object('game', jsonb_build_object('matchup','TEX @ LAA')))
on conflict do nothing;
