# Node-RED flows

This folder is mounted as `/data` in the Node-RED container (see `docker-compose.yml`).

| File | Content |
|---|---|
| `flows/sales-purchase-dashboard.json` | Employee dashboard: customers, sales orders (confirm, cancel, invoice, PDF, delivery date) and purchase orders |
| `flows/customer-portal-kpi.json` | Customer portal (my orders, quotation actions, delivery date, invoice PDF, messages) and KPI dashboards |

## Getting started

1. `docker compose up -d`, then open http://localhost:1880.
2. Menu → *Manage palette* → install the nodes used by the flows:
   `@flowfuse/node-red-dashboard`, `node-red-dashboard`, `node-red-node-ui-list`,
   `node-red-node-mysql`, `node-red-contrib-mysql-config`.
3. Menu → *Import* → select one of the files in `flows/`, then *Deploy*.
4. The flows call the API at `http://host.docker.internal:8000`, which works unchanged with
   docker compose.
5. The portal and KPI flows use a MySQL database. Database credentials were removed from the
   exported files: open the MySQL configuration nodes and enter your own. Node-RED then stores
   them in `flows_cred.json`, which is ignored by Git.
