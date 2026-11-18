-- Tables used by the Node-RED customer portal and KPI dashboards.
-- user_id / customer_id are Odoo partner ids (res.partner).

CREATE TABLE IF NOT EXISTS user_messages (
    message_id      INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT          NOT NULL,
    message_content TEXT         NOT NULL,
    message_type    VARCHAR(20)  NOT NULL DEFAULT 'question', -- question, incident, complaint, suggestion, praise
    order_name      VARCHAR(30)  NULL,                       -- Odoo order the message is about, if any
    message_status  VARCHAR(20)  NOT NULL DEFAULT 'sent',   -- sent, replied
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reply_content   TEXT         NULL,
    replied_at      DATETIME     NULL,
    INDEX idx_messages_user (user_id),
    INDEX idx_messages_created (created_at)
);

CREATE TABLE IF NOT EXISTS kpi_web_traffic (
    visit_id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id           INT           NULL,
    ip_address        VARCHAR(45)   NOT NULL,
    visit_date        DATE          NOT NULL,
    visit_start_time  DATETIME      NOT NULL,
    duration_minutes  DECIMAL(6, 2) NOT NULL DEFAULT 0,
    click_count       INT           NOT NULL DEFAULT 0,
    INDEX idx_traffic_date (visit_date)
);

CREATE TABLE IF NOT EXISTS online_quotes (
    quote_id      INT AUTO_INCREMENT PRIMARY KEY,
    order_name    VARCHAR(30) NOT NULL,
    customer_id   INT         NOT NULL,
    created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_confirmed  TINYINT(1)  NOT NULL DEFAULT 0,
    INDEX idx_quotes_created (created_at)
);

CREATE TABLE IF NOT EXISTS delivery_records (
    record_id             INT AUTO_INCREMENT PRIMARY KEY,
    order_name            VARCHAR(30) NOT NULL,
    customer_id           INT         NOT NULL,
    delivery_date         DATE        NOT NULL,   -- promised date
    actual_delivery_date  DATE        NULL        -- NULL = not delivered yet
);

-- Requests from customers to move the delivery date of a confirmed order.
-- The company approves (the new date is written to Odoo through the API) or rejects them.
CREATE TABLE IF NOT EXISTS delivery_change_requests (
    request_id      INT AUTO_INCREMENT PRIMARY KEY,
    order_name      VARCHAR(30)  NOT NULL,
    customer_id     INT          NOT NULL,
    previous_date   DATETIME     NULL,        -- scheduled date when the request was made (local time)
    requested_date  DATETIME     NOT NULL,    -- date asked by the customer (local time)
    reason          TEXT         NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',   -- pending, approved, rejected
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at      DATETIME     NULL,
    decision_note   TEXT         NULL,
    INDEX idx_requests_customer (customer_id),
    INDEX idx_requests_status (status)
);
