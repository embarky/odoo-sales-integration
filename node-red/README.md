# Node-RED flows

`flows.json` contains five tabs:

| Tab | Dashboard | Content |
|---|---|---|
| sales | `/ui` | Employee dashboard: customers, sales orders, confirm / cancel, invoice, PDF, delivery date |
| purchase | `/ui` | Employee dashboard: vendors and purchase orders |
| Customer - Interface | `/dashboard` | Customer portal: my orders, order details, quotation actions, delivery date, invoice PDF, messages |
| Customers Messages | `/dashboard` | Sales manager view of customer messages, with replies |
| KPI | `/dashboard` | KPI dashboards: traffic, quotations, deliveries, messages |

The `Dockerfile` builds Node-RED with the nodes the flows need. With `docker compose up`,
this folder is mounted as `/data`, so changes deployed from the editor are saved in
`flows.json` here.

The flows call the API at `http://api:8000` and use the MySQL service `mysql` of the
compose file. `flows_cred.json` holds the demo database login (`saturne` / `saturne`) in
clear text so the demo runs without setup; for real data, set `credentialSecret` in
`settings.js` and keep `flows_cred.json` out of version control.
