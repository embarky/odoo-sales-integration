# Node-RED flows

`flows.json` contains five tabs:

| Tab | Dashboard | Content |
|---|---|---|
| sales | `/ui` | Employee dashboard: customers, sales orders, confirm / cancel, invoice, PDF, delivery date |
| purchase | `/ui` | Employee dashboard: vendors and purchase orders |
| Customer Portal | `/dashboard/portal` | Customer self-service: orders and quotations, edit quotation lines, accept / decline, delivery date accept or change request, problem reports, messages and replies, order and invoice PDFs |
| Service Desk | `/dashboard/service-desk` | Employees: reply to customer messages, approve or reject delivery date requests (approval updates Odoo) |
| KPI | `/dashboard/page1` | KPI dashboards: traffic, quotations, deliveries; message KPIs are on the service desk page |

### How the portal and the service desk work

Each page is one Vue template (Dashboard 2.0 `ui-template`). A click sends
`{topic: <action>, payload}` to a function node (*Portal actions* / *Desk actions*) that turns it
into a call to the integration API or a MySQL query. The answer goes through *API result* /
*Database result*, which reply to the browser and trigger follow-ups (for example: after a
quotation is confirmed, the order and the order list are reloaded and the confirmation is
logged in `online_quotes` for the KPIs).

Answers carry `msg._client`, and `ui-template` is listed in the dashboard's
`acceptsClientConfig`, so each answer only reaches the browser session that asked for it.
Errors from the API (for example *nothing to invoice*) are shown to the user as they come from Odoo.

PDFs are served by Node-RED at `/pdf/order/:id`, `/pdf/invoice/:id` and `/pdf/purchase/:id`,
so the browser does not need to reach the API directly.

In the `/ui` employee dashboard, the order clicked in a list is kept in the flow context,
each button checks that the order is in the right state, and the API's answer is shown as a
notification before the lists are reloaded.

The `Dockerfile` builds Node-RED with the nodes the flows need. With `docker compose up`,
this folder is mounted as `/data`, so changes deployed from the editor are saved in
`flows.json` here.

The flows call the API at `$API_URL` (default `http://api:8000`) and use the MySQL service `mysql` of the
compose file. `flows_cred.json` holds the demo database login (`saturne` / `saturne`) in
clear text so the demo runs without setup; for real data, set `credentialSecret` in
`settings.js` and keep `flows_cred.json` out of version control.
