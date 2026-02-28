-- Migration 001: add unauthenticated_user_id FK to user table
ALTER TABLE `user`
    ADD COLUMN unauthenticated_user_id CHAR(36) NULL AFTER role,
    ADD CONSTRAINT fk_user_unauthenticated_user
        FOREIGN KEY (unauthenticated_user_id)
        REFERENCES unauthenticated_user_api_usage(user_id)
        ON DELETE SET NULL;
