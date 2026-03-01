-- Migration 001: add unauthenticated_user_id FK to user table
ALTER TABLE `user`
    ADD COLUMN unauthenticated_user_id CHAR(36) NULL AFTER role,
    ADD CONSTRAINT fk_user_unauthenticated_user
        FOREIGN KEY (unauthenticated_user_id)
        REFERENCES unauthenticated_user_api_usage(user_id)
        ON DELETE SET NULL;

-- Migration 001: add type column to folder table
ALTER TABLE folder
    ADD COLUMN type ENUM('BOOKMARK', 'PDF') NOT NULL DEFAULT 'BOOKMARK' AFTER name;

-- Backfill existing records
UPDATE folder SET type = 'BOOKMARK';

-- Migration 001: update folder ownership columns (nullable user_id + unauthenticated_user_id)
ALTER TABLE folder
    MODIFY COLUMN user_id CHAR(36) NULL,
    ADD COLUMN unauthenticated_user_id CHAR(36) NULL AFTER user_id,
    ADD INDEX idx_unauth_user_id (unauthenticated_user_id),
    ADD INDEX idx_unauth_user_parent (unauthenticated_user_id, parent_id),
    ADD CONSTRAINT fk_folder_unauth_user
        FOREIGN KEY (unauthenticated_user_id)
        REFERENCES unauthenticated_user_api_usage(user_id)
        ON DELETE SET NULL;

-- Migration 001: make created_by nullable and add unauthenticated_user_id to pdf table
-- created_by FK → user.id (existing, now nullable)
-- unauthenticated_user_id FK → unauthenticated_user_api_usage.user_id (new)
ALTER TABLE pdf
    MODIFY COLUMN created_by CHAR(36) NULL,
    ADD COLUMN unauthenticated_user_id CHAR(36) NULL AFTER created_by,
    ADD INDEX idx_unauth_user_id (unauthenticated_user_id),
    ADD CONSTRAINT fk_pdf_unauth_user
        FOREIGN KEY (unauthenticated_user_id)
        REFERENCES unauthenticated_user_api_usage(user_id)
        ON DELETE SET NULL;

-- Migration 001: make entity_id nullable in file_upload table
ALTER TABLE file_upload
    MODIFY COLUMN entity_id CHAR(36) NULL;

-- Migration 002: add folder_id FK to pdf table
ALTER TABLE pdf
    ADD COLUMN folder_id CHAR(36) NULL AFTER unauthenticated_user_id,
    ADD INDEX idx_folder_id (folder_id),
    ADD CONSTRAINT fk_pdf_folder
        FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE SET NULL;
