'use strict';

const path = require('node:path');

const projectDirectory = __dirname;

module.exports = {
  apps: [
    {
      name: 'wca-competition-reminder',
      cwd: projectDirectory,
      script: path.join(projectDirectory, '.venv', 'bin', 'python'),
      args: [
        '-m',
        'wca_competition_reminder',
        '--config',
        path.join(projectDirectory, 'config.toml'),
        '--smtp-password-file',
        path.join(projectDirectory, 'smtp_password'),
        'run',
      ],
      interpreter: 'none',
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      watch: false,
      min_uptime: 10000,
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 300000,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      out_file: '/dev/null',
      error_file: '/dev/null',
      env: {
        PYTHONDONTWRITEBYTECODE: '1',
        PYTHONUNBUFFERED: '1',
      },
    },
    {
      name: 'wca-competition-reminder-web',
      cwd: projectDirectory,
      script: path.join(projectDirectory, '.venv', 'bin', 'python'),
      args: [
        '-m',
        'wca_competition_reminder',
        '--config',
        path.join(projectDirectory, 'config.toml'),
        '--smtp-password-file',
        path.join(projectDirectory, 'smtp_password'),
        'web',
        '--host',
        '127.0.0.1',
        '--port',
        '8080',
      ],
      interpreter: 'none',
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      watch: false,
      min_uptime: 10000,
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 30000,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      out_file: '/dev/null',
      error_file: '/dev/null',
      env: {
        PYTHONDONTWRITEBYTECODE: '1',
        PYTHONUNBUFFERED: '1',
      },
    },
  ],
};
