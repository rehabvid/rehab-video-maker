/**
 * Fit a VRM's glasses accessory to the face.
 *
 * `assets/avatar/me.vrm` shipped its frame parented to the head bone with a
 * constant offset that is too far forward and too low: the lens floated in
 * front of the nose and sat under the brow instead of on it. That offset is
 * now baked into the asset with `tools/vrm/bake_glasses.mjs`, and the fitted
 * nodes carry `extras.linkzagGlassesFit`. For a baked model this helper does
 * nothing.
 *
 * A model that still carries a wrong offset is corrected at load time, in
 * memory:
 *   - the lens plane sits `gap` metres in front of the nose tip
 *   - the frame's vertical centre sits `lift` below the eye bones
 *
 * The placement is measured from the loaded scene, so a swapped model needs no
 * code change (and an already-correct pair moves by ~0).
 */
import * as THREE from 'three';

const GLASSES = /glass/i;

/** Marker written into `node.extras` by tools/vrm/bake_glasses.mjs. */
export const FIT_MARKER = 'linkzagGlassesFit';

function humanoidBone(vrm, name) {
  return vrm.humanoid?.getNormalizedBoneNode(name) || null;
}

/** Outermost glasses accessories parented under the head bone. */
export function findGlassesRoots(vrm) {
  const head = vrm.humanoid?.getRawBoneNode?.('head');
  if (!head) return [];
  const roots = [];
  head.traverse((o) => {
    if (o !== head && GLASSES.test(o.name || '')) roots.push(o);
  });
  // Keep only the outermost matches (a group plus its meshes are one object).
  return roots.filter((o) => !roots.some((p) => p !== o && isAncestor(p, o)));
}

export function fitGlasses(vrm, { gap = 0.004, scale = 1.08, lift = -0.005 } = {}) {
  const head = vrm.humanoid?.getRawBoneNode?.('head');
  if (!head) return null;

  const rootsTop = findGlassesRoots(vrm);
  if (!rootsTop.length) return null;

  const names = rootsTop.map((o) => o.name);
  if (rootsTop.some((o) => o.userData?.[FIT_MARKER])) {
    // Baked into the asset: applying the offset again would double it.
    return { baked: true, dy: 0, dz: 0, scale: 1, lift, glasses: names, face: null };
  }

  vrm.scene.updateMatrixWorld(true);
  const glassesBox = new THREE.Box3();
  for (const o of rootsTop) glassesBox.union(new THREE.Box3().setFromObject(o));

  // Face surface: the nose tip is the +Z extent of the face mesh.
  const face = vrm.scene.getObjectByName('Face') || findFace(vrm);
  const faceBox = new THREE.Box3();
  if (face) faceBox.setFromObject(face);
  else {
    // fall back to the head bone, excluding the glasses
    head.children.forEach((c) => {
      if (!GLASSES.test(c.name || '')) faceBox.union(new THREE.Box3().setFromObject(c));
    });
  }
  if (faceBox.isEmpty()) return null;

  const eyes = ['leftEye', 'rightEye']
    .map((n) => humanoidBone(vrm, n))
    .filter(Boolean)
    .map((b) => b.getWorldPosition(new THREE.Vector3()));
  const eyeY = eyes.length
    ? eyes.reduce((s, p) => s + p.y, 0) / eyes.length
    : (glassesBox.min.y + glassesBox.max.y) / 2;

  const gCenter = glassesBox.getCenter(new THREE.Vector3());
  const dy = eyeY - gCenter.y;
  const dz = -(glassesBox.max.z - (faceBox.max.z + gap));

  // Scale about the CURRENT lens centre, then place that centre on the target
  // (gap in front of the nose, `lift` above the eyes). Scaling about the
  // target plane instead would push the lens further away by `scale` x the
  // current error.
  const current = new THREE.Vector3(0, gCenter.y, glassesBox.max.z);
  const target = new THREE.Vector3(0, eyeY + lift, faceBox.max.z + gap);
  for (const o of rootsTop) {
    const q = new THREE.Quaternion();
    o.parent.getWorldQuaternion(q);
    const qInv = q.clone().invert();

    const pCur = o.parent.worldToLocal(current.clone());
    const pTgt = o.parent.worldToLocal(target.clone());
    const pos = o.position.clone();  // capture before overwriting

    // new = target + scale * (old - current)
    o.position.copy(pTgt).add(pos.clone().sub(pCur).multiplyScalar(scale));
    o.scale.multiplyScalar(scale);
  }
  vrm.scene.updateMatrixWorld(true);
  return {
    dy, dz, scale, lift,
    glasses: names,
    face: face?.name || null,
  };
}

function isAncestor(a, b) {
  for (let p = b.parent; p; p = p.parent) if (p === a) return true;
  return false;
}

function findFace(vrm) {
  let found = null;
  vrm.scene.traverse((o) => {
    if (!found && /face$/i.test(o.name || '')) found = o;
  });
  return found;
}
