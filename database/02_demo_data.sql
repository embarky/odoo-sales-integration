-- Demo data for the KPI dashboards. Dates are relative to the day the database is
-- created, so the "last 7 / 30 days" charts always have data.
-- Customers are partners of the Odoo demo database:
-- 8 Joel Willis, 9 Wood Corner, 10 Acme Corporation, 11 Gemini Furniture,
-- 12 Ready Mat, 15 Azure Interior, 16 Lumber Inc

-- 60 customer messages over the last 30 days, two thirds of them answered
INSERT INTO user_messages (user_id, message_content, message_type, message_status, created_at, reply_content, replied_at)
WITH RECURSIVE seq (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 60)
SELECT
    ELT(1 + (n * 3) % 7, 8, 9, 10, 11, 12, 15, 16),
    ELT(1 + n % 6,
        'Could you tell me when my order will be delivered?',
        'The invoice PDF does not show the discount we agreed on.',
        'It would be useful to see the delivery status in the portal.',
        'One of the chairs arrived damaged.',
        'Thank you, the delivery was very fast!',
        'Can I add two more desks to my last quotation?'),
    ELT(1 + n % 6, 'question', 'complaint', 'suggestion', 'incident', 'praise', 'question'),
    IF(n % 3 = 0, 'sent', 'replied'),
    TIMESTAMP(CURDATE() - INTERVAL (n % 30) DAY, MAKETIME(8 + n % 10, (n * 7) % 60, 0)),
    IF(n % 3 = 0, NULL, 'Thank you for your message, we are looking into it and will get back to you shortly.'),
    IF(n % 3 = 0, NULL, TIMESTAMP(CURDATE() - INTERVAL (n % 30) DAY, MAKETIME(8 + n % 10, (n * 7) % 60, 0))
                        + INTERVAL (1 + (n * 13) % 47) HOUR)
FROM seq;

-- 400 portal visits over the last 30 days
INSERT INTO kpi_web_traffic (user_id, ip_address, visit_date, visit_start_time, duration_minutes, click_count)
WITH RECURSIVE seq (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 400)
SELECT
    ELT(1 + n % 7, 8, 9, 10, 11, 12, 15, 16),
    CONCAT('185.12.', (n % 120) DIV 50, '.', (n % 120) + 1),          -- 120 distinct visitors
    CURDATE() - INTERVAL ((n * 17) % 30) DAY,
    TIMESTAMP(CURDATE() - INTERVAL ((n * 17) % 30) DAY,
              MAKETIME(ELT(1 + n % 12, 8, 9, 9, 10, 11, 13, 14, 14, 15, 16, 17, 20), (n * 11) % 60, 0)),
    ROUND(IF(n % 9 = 0, 0.5, 1 + ((n * 37) % 140) / 10), 2),
    IF(n % 9 = 0, 1, 2 + (n * 3) % 25)
FROM seq;

-- 90 quotations handled online this year, about 60 % confirmed
INSERT INTO online_quotes (order_name, customer_id, created_at, is_confirmed)
WITH RECURSIVE seq (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 90)
SELECT
    CONCAT('S', LPAD(100 + n, 5, '0')),
    ELT(1 + n % 7, 8, 9, 10, 11, 12, 15, 16),
    TIMESTAMP(CURDATE() - INTERVAL IF(n <= 40, n % 7, (n * 5) % 120) DAY, MAKETIME(9 + n % 8, (n * 19) % 60, 0)),
    IF(n % 5 < 3, 1, 0)
FROM seq;

-- 70 deliveries: most on time, some late, the most recent ones still pending
INSERT INTO delivery_records (order_name, customer_id, delivery_date, actual_delivery_date)
WITH RECURSIVE seq (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 70)
SELECT
    CONCAT('S', LPAD(100 + n, 5, '0')),
    ELT(1 + n % 7, 8, 9, 10, 11, 12, 15, 16),
    CURDATE() - INTERVAL (70 - n) DAY,
    CASE
        WHEN n > 62     THEN NULL                                                  -- pending
        WHEN n % 6 = 0  THEN CURDATE() - INTERVAL (70 - n) DAY + INTERVAL (1 + n % 4) DAY   -- late
        ELSE CURDATE() - INTERVAL (70 - n) DAY - INTERVAL (n % 2) DAY              -- on time
    END
FROM seq;

-- a short history for the demo customer Azure Interior (partner 15), shown in the portal
INSERT INTO user_messages (user_id, message_content, message_type, order_name, message_status, created_at, reply_content, replied_at)
VALUES
    (15, 'Two drawers of the last delivery have scratches on the front.', 'incident', 'S00029', 'replied',
     NOW() - INTERVAL 6 DAY, 'Sorry about that. Replacement fronts leave our warehouse on Monday.', NOW() - INTERVAL 5 DAY),
    (15, 'Can we get the invoices by e-mail as well?', 'question', NULL, 'sent', NOW() - INTERVAL 1 DAY, NULL, NULL);

INSERT INTO delivery_change_requests (order_name, customer_id, previous_date, requested_date, reason, status, created_at, decided_at, decision_note)
VALUES
    ('S00027', 15, TIMESTAMP(CURDATE() + INTERVAL 7 DAY, '10:00:00'), TIMESTAMP(CURDATE() + INTERVAL 12 DAY, '10:00:00'), 'Our showroom is closed for renovation next week.',
     'pending', NOW() - INTERVAL 2 HOUR, NULL, NULL);
