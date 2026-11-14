// Rates are observations, never default clinical values. Phase is continuous when rates change.
export const TAU = Math.PI * 2;
export function advancePhase(phase, rate, seconds, active = true) {
  return active && Number.isFinite(rate) && rate > 0 && Number.isFinite(seconds) && seconds > 0
    ? (phase + seconds * rate / 60 * TAU) % TAU : phase;
}
export const heartbeatScale = phase => 1 + .032 * Math.max(0, Math.sin(phase)) ** 8;
export const inspiration = phase => (1 - Math.cos(phase)) * .5;
export const smoothStep = t => 1 - (1 - Math.max(0, Math.min(1, t))) ** 3;
export const focusTargets = {
  brain: { region: 'SANS-01', label: 'Brain', meshes: ['BRAIN'], pin: 'pin-brain' },
  eyes: { region: 'SANS-01', label: 'Eyes & optic nerves', meshes: ['EYE_LEFT', 'EYE_RIGHT', 'OPTIC_NERVE_LEFT', 'OPTIC_NERVE_RIGHT'], pin: 'pin-eyes' },
  heart: { region: 'CV-02', label: 'Heart', meshes: ['HEART'], pin: 'pin-heart' },
  lungs: { region: 'ECLSS-03', label: 'Lungs', meshes: ['LUNG_LEFT', 'LUNG_RIGHT'], pin: 'pin-lungs' },
  core: { region: 'RAD-04', label: 'Radiation / thermal', meshes: ['BODY_SURFACE'], pin: 'pin-core' }
};
export const targetForMesh = name => Object.keys(focusTargets).find(key => focusTargets[key].meshes.includes(name));
export function fitDistance(size, aspect, fov, padding = 1.08) {
  const tangent = Math.tan(fov * Math.PI / 360);
  return Math.max(size.y / (2 * tangent), size.x / (2 * tangent * Math.max(.1, aspect))) * padding + size.z / 2;
}
export function visualStyle(name, status, selected, focused) {
  const skin = name === 'BODY_SURFACE', eye = name.startsWith('EYE_');
  const nerve = name.startsWith('OPTIC_NERVE_');
  const nominal = skin ? 0x27bde0 : eye ? 0x409bb4 : nerve ? 0x56c9da : name === 'BRAIN' ? 0xa69cdd : name === 'HEART' ? 0xb398cf : 0x67b3d7;
  const alert = status === 'red' || status === 'amber';
  const color = status === 'red' ? 0xff657a : status === 'amber' ? 0xffbf69 : selected ? 0xb7f2ff : status === 'unknown' ? 0x607c9b : nominal;
  let opacity = skin ? .055 : eye ? .14 : nerve ? .65 : name === 'BRAIN' ? .4 : name.startsWith('LUNG') ? .42 : .8;
  if (eye && alert) opacity = .4;
  if (focused) opacity = selected ? (skin ? .13 : eye ? .64 : .92) : skin ? .018 : alert ? .14 : .055;
  return { color, opacity, emissive: eye ? .018 : selected ? .18 : .07 };
}
