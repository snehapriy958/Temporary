/**
 * frontend/src/utils/coordinateTransform.js
 *
 * Phase 3B Stage 2: Geographic & Coordinate Transformation Utility.
 * Translates Eclipse SUMO 2D/3D Cartesian coordinates and navigational bearings
 * into Three.js local Cartesian coordinates (Y-up, right-handed) and Euler rotations.
 *
 * Ground Truth Conventions:
 *   - SUMO Cartesian: Right-handed. +X = East, +Y = North, +Z = Up (planar 0).
 *   - SUMO Heading: Degrees [0, 360), measured clockwise from North (+Y).
 *   - Three.js World: Right-handed. +X = East, +Y = Up (Elevation), +Z = South (Towards Viewer).
 *   - Vehicle Model Local Forward Axis: Canonical +Z_local = (0, 0, 1).
 *   - Scene Anchor: Central Silk Board (J2) at SUMO (2185.00, 3540.00).
 *
 * All illustrative elevations (flyovers/underpasses) are kept strictly separate from
 * verified horizontal SUMO geometry.
 */

export const DEFAULT_SCENE_ANCHOR = Object.freeze({
  name: 'Central Silk Board (J2)',
  sumo_x: 2185.00,
  sumo_y: 3540.00,
  sumo_z: 0.00,
  wgs84_lon: 77.62287,
  wgs84_lat: 12.91724,
});

/**
 * Model forward axis orientation offsets relative to canonical +Z_local (0, 0, 1).
 */
export const MODEL_ORIENTATION_OFFSETS = Object.freeze({
  CANONICAL_Z_FORWARD: 0.0,              // Mesh authored with +Z pointing forward
  CAMERA_CONVENTION_MINUS_Z: Math.PI,    // Mesh authored with -Z pointing forward (180 deg)
  CAD_THREEJS_X_FORWARD: -Math.PI / 2,   // Mesh authored with +X pointing forward (-90 deg)
});

/**
 * Validates that an input is a finite number.
 * @param {*} value
 * @param {string} name
 * @returns {number}
 */
function assertFiniteNumber(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`CoordinateTransformError: '${name}' must be a finite number, received: ${value}`);
  }
  return value;
}

/**
 * Converts SUMO Cartesian coordinates to Three.js right-handed local coordinates.
 *
 * Equations:
 *   X_three = x_sumo - anchor.sumo_x
 *   Y_three = z_sumo + illustrativeElevation
 *   Z_three = anchor.sumo_y - y_sumo
 *
 * @param {number} sumoX - SUMO Easting (meters)
 * @param {number} sumoY - SUMO Northing (meters)
 * @param {number} [sumoZ=0.0] - Verified SUMO elevation (meters, planar 0.0)
 * @param {number} [illustrativeElevation=0.0] - Optional architectural clearance offset (meters)
 * @param {object} [anchor=DEFAULT_SCENE_ANCHOR] - Scene anchor definition
 * @returns {{x: number, y: number, z: number}} Three.js local coordinates in meters
 */
export function sumoToThreeCoords(
  sumoX,
  sumoY,
  sumoZ = 0.0,
  illustrativeElevation = 0.0,
  anchor = DEFAULT_SCENE_ANCHOR
) {
  const x = assertFiniteNumber(sumoX, 'sumoX');
  const y = assertFiniteNumber(sumoY, 'sumoY');
  const z = assertFiniteNumber(sumoZ, 'sumoZ');
  const elev = assertFiniteNumber(illustrativeElevation, 'illustrativeElevation');
  const ax = assertFiniteNumber(anchor?.sumo_x, 'anchor.sumo_x');
  const ay = assertFiniteNumber(anchor?.sumo_y, 'anchor.sumo_y');

  return {
    x: x - ax,
    y: z + elev,
    z: ay - y,
  };
}

/**
 * Inverts Three.js local coordinates back into original SUMO Cartesian coordinates.
 *
 * Equations:
 *   x_sumo = X_three + anchor.sumo_x
 *   y_sumo = anchor.sumo_y - Z_three
 *   z_sumo = Y_three - illustrativeElevation
 *
 * @param {number} threeX - Three.js X (East)
 * @param {number} threeY - Three.js Y (Up)
 * @param {number} threeZ - Three.js Z (South)
 * @param {number} [illustrativeElevation=0.0] - Optional architectural clearance offset (meters)
 * @param {object} [anchor=DEFAULT_SCENE_ANCHOR] - Scene anchor definition
 * @returns {{x: number, y: number, z: number}} Recovered SUMO Cartesian coordinates
 */
export function threeToSumoCoords(
  threeX,
  threeY,
  threeZ,
  illustrativeElevation = 0.0,
  anchor = DEFAULT_SCENE_ANCHOR
) {
  const tx = assertFiniteNumber(threeX, 'threeX');
  const ty = assertFiniteNumber(threeY, 'threeY');
  const tz = assertFiniteNumber(threeZ, 'threeZ');
  const elev = assertFiniteNumber(illustrativeElevation, 'illustrativeElevation');
  const ax = assertFiniteNumber(anchor?.sumo_x, 'anchor.sumo_x');
  const ay = assertFiniteNumber(anchor?.sumo_y, 'anchor.sumo_y');

  return {
    x: tx + ax,
    y: ay - tz,
    z: ty - elev,
  };
}

/**
 * Transforms a navigational SUMO heading (degrees, clockwise from North) into an
 * Euler rotation angle around the Three.js vertical Y-axis (radians, counter-clockwise from East),
 * assuming a vehicle 3D model authored with canonical forward axis +Z_local = (0, 0, 1).
 *
 * Derivation:
 *   SUMO bearing theta in [0, 360) clockwise from North:
 *     North (0 deg)   -> direction (0, 0, -1) along -Z_world
 *     East (90 deg)   -> direction (1, 0, 0) along +X_world
 *     South (180 deg) -> direction (0, 0, 1) along +Z_world
 *     West (270 deg)  -> direction (-1, 0, 0) along -X_world
 *
 *   Canonical mesh (+Z_local):
 *     Psi_base = PI - (theta * PI / 180)
 *     Psi_three = Psi_base + modelOffsetRad
 *
 * @param {number} sumoAngleDeg - Heading in degrees [0, 360)
 * @param {number} [modelOffsetRad=0.0] - Model authoring forward orientation offset (radians)
 * @returns {number} Euler yaw angle around Three.js Y-axis in radians, normalized to [-PI, +PI]
 */
export function sumoHeadingToThreeYaw(sumoAngleDeg, modelOffsetRad = 0.0) {
  const angle = assertFiniteNumber(sumoAngleDeg, 'sumoAngleDeg');
  const offset = assertFiniteNumber(modelOffsetRad, 'modelOffsetRad');

  // Convert degrees to radians
  const sumoRad = angle * (Math.PI / 180.0);
  const yawBase = Math.PI - sumoRad;
  const yawTotal = yawBase + offset;

  // Normalize to [-PI, +PI]
  return Math.atan2(Math.sin(yawTotal), Math.cos(yawTotal));
}

/**
 * Inverts an Euler yaw angle back to a SUMO navigational bearing in degrees [0, 360).
 *
 * @param {number} threeYawRad - Euler yaw angle in radians
 * @param {number} [modelOffsetRad=0.0] - Model authoring forward orientation offset (radians)
 * @returns {number} SUMO navigational heading in degrees [0, 360)
 */
export function threeYawToSumoHeading(threeYawRad, modelOffsetRad = 0.0) {
  const yaw = assertFiniteNumber(threeYawRad, 'threeYawRad');
  const offset = assertFiniteNumber(modelOffsetRad, 'modelOffsetRad');

  const yawBase = yaw - offset;
  let deg = 180.0 - (yawBase * (180.0 / Math.PI));

  // Normalize to [0, 360)
  deg = deg % 360.0;
  if (deg < 0) {
    deg += 360.0;
  }
  // Clamp negative zero
  return deg === 0 ? 0.0 : deg;
}

/**
 * Computes the Three.js unit world direction vector (dX, dY, dZ) from a SUMO heading.
 *
 * @param {number} sumoAngleDeg - Heading in degrees [0, 360)
 * @returns {{x: number, y: number, z: number}} Three.js unit world direction vector
 */
export function sumoHeadingToThreeDirection(sumoAngleDeg) {
  const angle = assertFiniteNumber(sumoAngleDeg, 'sumoAngleDeg');
  const rad = angle * (Math.PI / 180.0);
  return {
    x: Math.sin(rad),
    y: 0.0,
    z: -Math.cos(rad),
  };
}

/**
 * Transforms an array-based coordinate tuple [x, y] or [x, y, z] to Three.js coordinates.
 *
 * @param {Array<number>} pt - Point [x, y] or [x, y, z] in SUMO space
 * @param {number} [illustrativeElevation=0.0] - Optional illustrative elevation offset
 * @param {object} [anchor=DEFAULT_SCENE_ANCHOR] - Scene anchor
 * @returns {[number, number, number]} Transformed [X_three, Y_three, Z_three]
 */
export function transformPoint(pt, illustrativeElevation = 0.0, anchor = DEFAULT_SCENE_ANCHOR) {
  if (!Array.isArray(pt) || pt.length < 2) {
    throw new TypeError(`CoordinateTransformError: Point must be an array of at least 2 numbers, received: ${JSON.stringify(pt)}`);
  }
  const x = pt[0];
  const y = pt[1];
  const z = pt.length > 2 ? pt[2] : 0.0;
  const res = sumoToThreeCoords(x, y, z, illustrativeElevation, anchor);
  return [res.x, res.y, res.z];
}

/**
 * Inverts a Three.js point [X, Y, Z] back to SUMO [x, y, z].
 *
 * @param {Array<number>} threePt - Point [X, Y, Z] in Three.js space
 * @param {number} [illustrativeElevation=0.0] - Optional illustrative elevation offset
 * @param {object} [anchor=DEFAULT_SCENE_ANCHOR] - Scene anchor
 * @returns {[number, number, number]} Recovered SUMO [x, y, z]
 */
export function inverseTransformPoint(threePt, illustrativeElevation = 0.0, anchor = DEFAULT_SCENE_ANCHOR) {
  if (!Array.isArray(threePt) || threePt.length < 3) {
    throw new TypeError(`CoordinateTransformError: Three.js point must be an array of 3 numbers, received: ${JSON.stringify(threePt)}`);
  }
  const res = threeToSumoCoords(threePt[0], threePt[1], threePt[2], illustrativeElevation, anchor);
  return [res.x, res.y, res.z];
}

/**
 * Transforms a complete lane shape (array of coordinate tuples) into Three.js space.
 * Preserves point ordering and Euclidean lengths.
 *
 * @param {Array<Array<number>>} shape - Array of [x, y] or [x, y, z] points
 * @param {number} [illustrativeElevation=0.0] - Optional elevation offset
 * @param {object} [anchor=DEFAULT_SCENE_ANCHOR] - Scene anchor
 * @returns {Array<[number, number, number]>} Transformed Three.js points
 */
export function transformLaneShape(shape, illustrativeElevation = 0.0, anchor = DEFAULT_SCENE_ANCHOR) {
  if (!Array.isArray(shape)) {
    throw new TypeError('CoordinateTransformError: Lane shape must be an array of points.');
  }
  return shape.map(pt => transformPoint(pt, illustrativeElevation, anchor));
}

/**
 * Transforms a junction boundary polygon (array of [x, y] points) into Three.js space.
 *
 * @param {Array<Array<number>>} polygon - Array of [x, y] boundary vertices
 * @param {number} [illustrativeElevation=0.0] - Optional elevation offset
 * @param {object} [anchor=DEFAULT_SCENE_ANCHOR] - Scene anchor
 * @returns {Array<[number, number, number]>} Transformed Three.js polygon vertices
 */
export function transformJunctionShape(polygon, illustrativeElevation = 0.0, anchor = DEFAULT_SCENE_ANCHOR) {
  if (!Array.isArray(polygon)) {
    throw new TypeError('CoordinateTransformError: Junction shape must be an array of vertices.');
  }
  return polygon.map(pt => transformPoint(pt, illustrativeElevation, anchor));
}

/**
 * Computes 2D Euclidean distance between two points in either coordinate system.
 * Useful for validating isometric metric preservation.
 *
 * @param {{x: number, y?: number, z?: number}} p1
 * @param {{x: number, y?: number, z?: number}} p2
 * @param {'xy'|'xz'} [plane='xy']
 * @returns {number} Metric distance
 */
export function computeDistance(p1, p2, plane = 'xy') {
  if (plane === 'xy') {
    const dx = p2.x - p1.x;
    const dy = (p2.y ?? 0) - (p1.y ?? 0);
    return Math.hypot(dx, dy);
  } else {
    const dx = p2.x - p1.x;
    const dz = (p2.z ?? 0) - (p1.z ?? 0);
    return Math.hypot(dx, dz);
  }
}
