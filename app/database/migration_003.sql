-- Migration 009: create custom_user_prompt table
CREATE TABLE IF NOT EXISTS custom_user_prompt (
    id          CHAR(36)      PRIMARY KEY DEFAULT (UUID()),
    user_id     CHAR(36)      NOT NULL,
    title       VARCHAR(200)  NOT NULL,
    description TEXT          NOT NULL,
    is_hidden   BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id            (user_id),
    INDEX idx_user_id_is_hidden  (user_id, is_hidden),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 009: create custom_user_prompt_share table
CREATE TABLE IF NOT EXISTS custom_user_prompt_share (
    id                      CHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    custom_user_prompt_id   CHAR(36)  NOT NULL,
    shared_to               CHAR(36)  NOT NULL,
    is_hidden               BOOLEAN   NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_prompt_shared_to (custom_user_prompt_id, shared_to),
    INDEX idx_shared_to            (shared_to),
    INDEX idx_custom_user_prompt_id (custom_user_prompt_id),
    FOREIGN KEY (custom_user_prompt_id) REFERENCES custom_user_prompt(id) ON DELETE CASCADE,
    FOREIGN KEY (shared_to)            REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create pdf_text_chat (conversation record anchored to a text selection on a PDF)
CREATE TABLE IF NOT EXISTS pdf_text_chat (
    id                          CHAR(36)    PRIMARY KEY DEFAULT (UUID()),
    pdf_id                      CHAR(36)    NOT NULL,
    user_id                     CHAR(36)    NOT NULL,
    start_text_pdf_page_number  INT         NOT NULL,
    end_text_pdf_page_number    INT         NOT NULL,
    start_text                  VARCHAR(50) NOT NULL,
    end_text                    VARCHAR(50) NOT NULL,
    created_at                  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_pdf_id   (pdf_id),
    INDEX idx_user_id  (user_id),
    INDEX idx_pdf_user (pdf_id, user_id),
    FOREIGN KEY (pdf_id)  REFERENCES pdf(id)  ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create new pdf_text_chat_history (individual USER/SYSTEM messages within a conversation)
CREATE TABLE IF NOT EXISTS pdf_text_chat_history (
    id               CHAR(36)               PRIMARY KEY DEFAULT (UUID()),
    pdf_text_chat_id CHAR(36)               NOT NULL,
    who              ENUM('USER', 'SYSTEM')  NOT NULL,
    content          TEXT                    NOT NULL,
    created_at       TIMESTAMP               NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pdf_text_chat_id      (pdf_text_chat_id),
    INDEX idx_pdf_text_chat_created (pdf_text_chat_id, created_at),
    FOREIGN KEY (pdf_text_chat_id) REFERENCES pdf_text_chat(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
