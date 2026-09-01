const container = document.getElementById('game-container');
const playerHealthEl = document.getElementById('player-health');
const enemyHealthEl = document.getElementById('enemy-health');
const messageEl = document.getElementById('message');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1220);

const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 200);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
container.appendChild(renderer.domElement);

const light = new THREE.DirectionalLight(0xffffff, 1.0);
light.position.set(5, 10, 5);
light.castShadow = true;
light.shadow.mapSize.width = 2048;
light.shadow.mapSize.height = 2048;
scene.add(light);

const ambient = new THREE.AmbientLight(0x9999aa, 0.4);
scene.add(ambient);

const arenaSize = 40;
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(arenaSize, arenaSize, 10, 10),
  new THREE.MeshStandardMaterial({ color: 0x2b3b54, roughness: 0.9 })
);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

const wallMaterial = new THREE.MeshStandardMaterial({ color: 0x1c2a3d, roughness: 0.8 });
const wallDepth = 1;
const wallHeight = 6;
const wallPositions = [
  { x: 0, y: wallHeight / 2, z: -arenaSize / 2, rotY: 0, scaleX: arenaSize, scaleZ: wallDepth },
  { x: 0, y: wallHeight / 2, z: arenaSize / 2, rotY: 0, scaleX: arenaSize, scaleZ: wallDepth },
  { x: -arenaSize / 2, y: wallHeight / 2, z: 0, rotY: 0, scaleX: wallDepth, scaleZ: arenaSize },
  { x: arenaSize / 2, y: wallHeight / 2, z: 0, rotY: 0, scaleX: wallDepth, scaleZ: arenaSize },
];
wallPositions.forEach((cfg) => {
  const wall = new THREE.Mesh(
    new THREE.BoxGeometry(cfg.scaleX, cfg.scaleY, cfg.scaleZ),
    wallMaterial
  );
  wall.position.set(cfg.x, cfg.y, cfg.z);
  wall.receiveShadow = true;
  scene.add(wall);
});

const createPlayer = (color) => {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(1.2, 1.8, 1.2),
    new THREE.MeshStandardMaterial({ color })
  );
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
};

const player = createPlayer(0x52e5ff);
player.position.set(0, 0.9, 10);
scene.add(player);

const enemy = createPlayer(0xff605c);
enemy.position.set(0, 0.9, -10);
scene.add(enemy);

const bullets = [];
const enemyBullets = [];
let lastEnemyShot = 0;
let playerHealth = 100;
let enemyHealth = 100;
let gameOver = false;
let keys = { ArrowUp:false, ArrowDown:false, ArrowLeft:false, ArrowRight:false, Space:false };
let shootCooldown = 0;
let time = 0;

const cameraOffset = new THREE.Vector3(0, 6, 12);
const targetOffset = new THREE.Vector3(0, 1.5, 0);

const updateHUD = () => {
  playerHealthEl.textContent = Math.max(0, Math.floor(playerHealth));
  enemyHealthEl.textContent = Math.max(0, Math.floor(enemyHealth));
};

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const shootBullet = (origin, direction, owner) => {
  const bullet = new THREE.Mesh(
    new THREE.SphereGeometry(0.18, 10, 10),
    new THREE.MeshStandardMaterial({ color: owner === 'player' ? 0xa6f1ff : 0xffb07c })
  );
  bullet.position.copy(origin);
  bullet.userData = {
    direction: direction.clone().normalize(),
    owner,
    prevPosition: origin.clone(),
  };
  scene.add(bullet);
  bullets.push(bullet);
};

const createExplosion = (position) => {
  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(1.2, 12, 12),
    new THREE.MeshBasicMaterial({ color: 0xffcc88, transparent: true, opacity: 0.6 })
  );
  glow.position.copy(position);
  scene.add(glow);
  const start = performance.now();
  const lifetime = 320;
  const animateGlow = () => {
    const elapsed = performance.now() - start;
    if (elapsed > lifetime) {
      scene.remove(glow);
      glow.geometry.dispose();
      glow.material.dispose();
      return;
    }
    glow.scale.setScalar(1 + elapsed / lifetime);
    glow.material.opacity = 0.6 * (1 - elapsed / lifetime);
    requestAnimationFrame(animateGlow);
  };
  animateGlow();
};

const collideBox = (meshA, meshB, radius = 1, prevPosition = null) => {
  const start = prevPosition || meshA.position;
  const end = meshA.position;
  const center = meshB.position;
  const segment = end.clone().sub(start);
  const toCenter = center.clone().sub(start);
  const segmentLength = segment.length();
  if (segmentLength === 0) {
    return start.distanceTo(center) < radius;
  }
  const direction = segment.clone().normalize();
  const projection = clamp(toCenter.dot(direction), 0, segmentLength);
  const closestPoint = start.clone().add(direction.multiplyScalar(projection));
  return closestPoint.distanceTo(center) < radius;
};

const firePlayerBullet = () => {
  if (shootCooldown > 0) return;
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(player.quaternion);
  const origin = player.position.clone().add(forward.clone().multiplyScalar(1.4)).add(new THREE.Vector3(0, 0.4, 0));
  shootBullet(origin, forward, 'player');
  shootCooldown = 0.35;
};

const fireEnemyBullet = () => {
  const dir = player.position.clone().sub(enemy.position).normalize();
  const origin = enemy.position.clone().add(dir.clone().multiplyScalar(1.4)).add(new THREE.Vector3(0, 0.4, 0));
  shootBullet(origin, dir, 'enemy');
};

const handleControls = (delta) => {
  const moveSpeed = 8;
  const turnSpeed = 2.8;
  if (keys.ArrowLeft) {
    player.rotation.y += turnSpeed * delta;
  }
  if (keys.ArrowRight) {
    player.rotation.y -= turnSpeed * delta;
  }
  let forwardMove = 0;
  if (keys.ArrowUp) forwardMove = 1;
  if (keys.ArrowDown) forwardMove = -0.55;
  if (forwardMove !== 0) {
    const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(player.quaternion);
    player.position.addScaledVector(forward, moveSpeed * delta * forwardMove);
  }
  player.position.x = clamp(player.position.x, -arenaSize / 2 + 1.2, arenaSize / 2 - 1.2);
  player.position.z = clamp(player.position.z, -arenaSize / 2 + 1.2, arenaSize / 2 - 1.2);
  if (keys.Space) {
    firePlayerBullet();
  }
};

const updateEnemy = (delta) => {
  const targetDir = player.position.clone().sub(enemy.position);
  const distance = targetDir.length();
  const desiredAngle = Math.atan2(targetDir.x, targetDir.z);
  const currentAngle = enemy.rotation.y;
  let deltaAngle = desiredAngle - currentAngle;
  deltaAngle = ((deltaAngle + Math.PI) % (Math.PI * 2)) - Math.PI;
  enemy.rotation.y += clamp(deltaAngle, -delta * 1.8, delta * 1.8);
  if (distance > 5) {
    const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(enemy.quaternion);
    enemy.position.addScaledVector(forward, delta * 3.5);
  }
  enemy.position.x = clamp(enemy.position.x, -arenaSize / 2 + 1.2, arenaSize / 2 - 1.2);
  enemy.position.z = clamp(enemy.position.z, -arenaSize / 2 + 1.2, arenaSize / 2 - 1.2);
  if (time - lastEnemyShot > 1.1) {
    fireEnemyBullet();
    lastEnemyShot = time;
  }
};

const updateBullets = (delta) => {
  for (let i = bullets.length - 1; i >= 0; i--) {
    const bullet = bullets[i];
    const dir = bullet.userData.direction;
    const prevPos = bullet.userData.prevPosition.clone();
    bullet.position.addScaledVector(dir, delta * 32);
    bullet.userData.prevPosition.copy(bullet.position);

    const hitEnemy = bullet.userData.owner === 'player' && collideBox(bullet, enemy, 1.4, prevPos);
    const hitPlayer = bullet.userData.owner === 'enemy' && collideBox(bullet, player, 1.4, prevPos);
    const outOfBounds = Math.abs(bullet.position.x) > arenaSize / 2 + 2 || Math.abs(bullet.position.z) > arenaSize / 2 + 2;
    if (hitEnemy || hitPlayer || outOfBounds) {
      if (hitEnemy) {
        enemyHealth -= 18;
        createExplosion(bullet.position);
      }
      if (hitPlayer) {
        playerHealth -= 12;
        createExplosion(bullet.position);
      }
      scene.remove(bullet);
      bullet.geometry.dispose();
      bullet.material.dispose();
      bullets.splice(i, 1);
      continue;
    }
  }
};

const endGame = (message) => {
  gameOver = true;
  messageEl.textContent = message;
  updateHUD();
};

const updateScene = (delta) => {
  if (gameOver) {
    return;
  }
  handleControls(delta);
  updateEnemy(delta);
  updateBullets(delta);
  if (shootCooldown > 0) shootCooldown -= delta;
  if (playerHealth <= 0) {
    playerHealth = 0;
    endGame('Game Over — You were defeated. Refresh to restart.');
    return;
  }
  if (enemyHealth <= 0) {
    enemyHealth = 0;
    endGame('Victory — You defeated the enemy! Refresh to restart.');
    return;
  }
  updateHUD();
  const desiredCameraPos = player.position.clone().add(cameraOffset.clone().applyQuaternion(player.quaternion));
  camera.position.lerp(desiredCameraPos, 0.12);
  camera.lookAt(player.position.clone().add(targetOffset));
};

const animate = () => {
  requestAnimationFrame(animate);
  const currentTime = performance.now() / 1000;
  const delta = Math.min(0.04, currentTime - time);
  time = currentTime;
  updateScene(delta);
  renderer.render(scene, camera);
};

window.addEventListener('keydown', (event) => {
  if (event.code in keys) {
    keys[event.code] = true;
    event.preventDefault();
  }
});
window.addEventListener('keyup', (event) => {
  if (event.code in keys) {
    keys[event.code] = false;
    event.preventDefault();
  }
});
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

updateHUD();
animate();
