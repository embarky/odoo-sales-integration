FROM nodered/node-red:4.1.1-22

# Nodes used by the flows, at the versions they were built with
RUN npm install --no-audit --no-fund --omit=dev \
        @flowfuse/node-red-dashboard@1.29.0 \
        node-red-dashboard@3.6.6 \
        node-red-node-ui-list@0.3.6 \
        node-red-node-mysql@2.0.0
