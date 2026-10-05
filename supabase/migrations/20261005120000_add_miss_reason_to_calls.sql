-- AIE-83: store the last known SIP call status (sip.callStatus) when an
-- outbound call (reminder/reschedule) times out unanswered, so the dashboard
-- can show *why* a call was marked missed instead of just a bare "missed"
-- with no diagnostic signal.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS miss_reason text;
