# Node-RED flows

`flows.json` contains four tabs, all on Node-RED Dashboard 2.0 (`/dashboard`):

| Tab | Dashboard | Content |
|---|---|---|
| Customer Portal | `/dashboard/portal` | Customer self-service: orders and quotations, edit quotation lines, accept / decline, delivery date accept or change request, problem reports, messages and replies, order and invoice PDFs |
| Back Office | `/dashboard/back-office` | Employees: sales orders from quotation to payment (confirm, validate delivery, create and confirm invoice, register payment, cancel, PDFs) and purchase orders (confirm, cancel, vendor arrival date, PDF) |
| Service Desk | `/dashboard/service-desk` | Employees: reply to customer messages, approve or reject delivery date requests (approval updates Odoo) |
| KPI | `/dashboard/kpi` | KPI dashboards: traffic, quotations, deliveries; message KPIs are on the service desk page |

### How the pages work

Each page is one Vue template (Dashboard 2.0 `ui-template`). A click sends
`{topic: <action>, payload}` to a function node (*Portal actions*, *Back office actions*, *Desk actions*) that turns it
into a call to the integration API or a MySQL query. The answer goes through *API result* /
*Database result*, which reply to the browser and trigger follow-ups (for example: after a
quotation is confirmed, the order and the order list are reloaded and the confirmation is
logged in `online_quotes` for the KPIs).

Answers carry `msg._client`, and `ui-template` is listed in the dashboard's
`acceptsClientConfig`, so each answer only reaches the browser session that asked for it.
Errors from the API (for example *nothing to invoice*) are shown to the user as they come from Odoo.

PDFs are served by Node-RED at `/pdf/order/:id`, `/pdf/invoice/:id` and `/pdf/purchase/:id`,
so the browser does not need to reach the API directly.

The back office replaces the first version of the employee dashboard, which was built with the
first-generation Node-RED dashboard (`/ui`, no longer maintained). It covers the same actions and adds delivery,
invoice confirmation and payment, so the whole order-to-cash process of the BPMN model can be run
from one page. Odoo's own sample orders created before the Inventory app was installed do not
record deliveries, so Odoo reports nothing to invoice for them; the demo orders added by
`demo/seed_odoo.py` go through every step.

The `Dockerfile` builds Node-RED with the nodes the flows need. With `docker compose up`,
this folder is mounted as `/data`, so changes deployed from the editor are saved in
`flows.json` here.

The flows call the API at `$API_URL` (default `http://api:8000`) and use the MySQL service `mysql` of the
compose file. `flows_cred.json` holds the demo database login (`saturne` / `saturne`) in
clear text so the demo runs without setup; for real data, set `credentialSecret` in
`settings.js` and keep `flows_cred.json` out of version control.
