-- Migration 010: Change custom_user_prompt_share.shared_to to store email address directly
-- (mirrors the pdf_share pattern: no FK to user, just store the recipient email string)
--
-- Uses a stored procedure to dynamically find and drop the FK constraint on shared_to,
-- regardless of the auto-generated name InnoDB assigned it.

DROP PROCEDURE IF EXISTS migration_010_drop_fk;

DELIMITER $$
CREATE PROCEDURE migration_010_drop_fk()
BEGIN
    DECLARE fk_name VARCHAR(256) DEFAULT NULL;

    SELECT CONSTRAINT_NAME INTO fk_name
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA   = DATABASE()
      AND TABLE_NAME     = 'custom_user_prompt_share'
      AND COLUMN_NAME    = 'shared_to'
      AND REFERENCED_TABLE_NAME = 'user'
    LIMIT 1;

    IF fk_name IS NOT NULL THEN
        SET @sql = CONCAT('ALTER TABLE custom_user_prompt_share DROP FOREIGN KEY `', fk_name, '`');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL migration_010_drop_fk();
DROP PROCEDURE IF EXISTS migration_010_drop_fk;

ALTER TABLE custom_user_prompt_share
    MODIFY COLUMN shared_to VARCHAR(256) NOT NULL;
