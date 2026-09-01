import confetti from 'canvas-confetti';

export function triggerCardExplosion(element: HTMLElement) {
  if (typeof window === 'undefined') return;

  const rect = element.getBoundingClientRect();
  const x = (rect.left + rect.width / 2) / window.innerWidth;
  const y = (rect.top + rect.height / 2) / window.innerHeight;

  const colors = ['#ecad0a', '#209dd7', '#753991', '#032147', '#ffffff'];

  // Explosive burst 1
  confetti({
    particleCount: 50,
    spread: 70,
    origin: { x, y },
    colors,
    startVelocity: 30,
    scalar: 1.1,
    ticks: 150,
  });

  // Secondary burst for extra effect
  setTimeout(() => {
    confetti({
      particleCount: 30,
      angle: 90,
      spread: 100,
      origin: { x, y },
      colors,
      startVelocity: 20,
      scalar: 0.8,
      ticks: 120,
    });
  }, 100);
}
