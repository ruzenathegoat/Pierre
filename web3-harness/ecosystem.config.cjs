const path = require('node:path');

module.exports = {
  apps: [
    {
      name: 'hermes-discord',
      script: 'hermes',
      args: 'gateway',
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
    },
    {
      name: 'price-watcher',
      script: 'tsx',
      args: path.join(__dirname, 'src', 'watcher.ts'),
      cwd: __dirname,
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      env: {
        NODE_NO_WARNINGS: '1',
      },
    },
    {
      name: 'baw-keepalive',
      script: 'tsx',
      args: path.join(__dirname, 'src', 'baw-keepalive.ts'),
      cwd: __dirname,
      autorestart: false,
      cron_restart: '0 */6 * * *',
      env: {
        NODE_NO_WARNINGS: '1',
      },
    },
  ],
};

