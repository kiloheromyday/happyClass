const { spawnSync } = require('node:child_process');
const path = require('node:path');

for (const name of ['test_replay_interactions.cjs', 'test_insights_interactions.cjs', 'test_page_roles.cjs']) {
  const result = spawnSync(process.execPath, [path.join(__dirname, 'emotion', name)], { stdio: 'inherit' });
  if (result.status !== 0) process.exit(result.status || 1);
}
