ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS question_strategy JSONB NOT NULL DEFAULT
        '{"criticalness":3,"difficulty":3,"evidence_required":true,"follow_up_depth":1}'::jsonb;
