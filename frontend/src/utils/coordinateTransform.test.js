/**
 * frontend/src/utils/coordinateTransform.test.js
 *
 * Phase 3B Stage 2 Automated Test Suite:
 * Deterministically tests coordinate transformation, inverse recovery, cardinal directions,
 * vehicle model heading, distance preservation, junction placement, and error handling.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  DEFAULT_SCENE_ANCHOR,
  MODEL_ORIENTATION_OFFSETS,
  sumoToThreeCoords,
  threeToSumoCoords,
  sumoHeadingToThreeYaw,
  threeYawToSumoHeading,
  sumoHeadingToThreeDirection,
  transformPoint,
  inverseTransformPoint,
  transformLaneShape,
  transformJunctionShape,
  computeDistance,
} from './coordinateTransform.js';

// Load extracted corridor geometry for real-world integration validation
const geometryUrl = new URL('../data/corridorNetworkGeometry.json', import.meta.url);
const corridorData = JSON.parse(readFileSync(fileURLToPath(geometryUrl), 'utf-8'));

describe('Phase 3B Stage 2: Coordinate Transformation & Spatial Validation', () => {

  describe('1. Basic Coordinate Transformation & Scene Anchor', () => {
    it('maps SUMO scene anchor exactly to Three.js origin (0, 0, 0)', () => {
      const res = sumoToThreeCoords(
        DEFAULT_SCENE_ANCHOR.sumo_x,
        DEFAULT_SCENE_ANCHOR.sumo_y,
        DEFAULT_SCENE_ANCHOR.sumo_z,
        0.0
      );
      assert.strictEqual(res.x, 0.0);
      assert.strictEqual(res.y, 0.0);
      assert.strictEqual(res.z, 0.0);
    });

    it('documents the exact offset between scene origin and J2 junction centroid', () => {
      const j2 = corridorData.junctions[corridorData.keyJunctions.J2.id];
      const res = sumoToThreeCoords(j2.x, j2.y, 0.0);

      // Centroid is at (2186.13, 3523.88)
      const expectedX = 2186.13 - 2185.00; // +1.13m East
      const expectedZ = 3540.00 - 3523.88; // +16.12m South (towards viewer)

      assert.ok(Math.abs(res.x - expectedX) < 1e-6);
      assert.ok(Math.abs(res.z - expectedZ) < 1e-6);
      assert.strictEqual(res.y, 0.0);

      // Euclidean offset is approximately 16.16 meters
      const offsetDist = Math.hypot(res.x, res.z);
      assert.ok(Math.abs(offsetDist - 16.1594) < 1e-3);
    });

    it('correctly incorporates illustrative elevation offsets into Three.js Y without altering X or Z', () => {
      const ground = sumoToThreeCoords(2185.00, 3540.00, 0.0, 0.0);
      const flyover = sumoToThreeCoords(2185.00, 3540.00, 0.0, 7.50);
      const underpass = sumoToThreeCoords(2185.00, 3540.00, 0.0, -4.50);

      assert.strictEqual(ground.x, flyover.x);
      assert.strictEqual(ground.z, flyover.z);
      assert.strictEqual(flyover.y, 7.50);

      assert.strictEqual(ground.x, underpass.x);
      assert.strictEqual(ground.z, underpass.z);
      assert.strictEqual(underpass.y, -4.50);
    });
  });

  describe('2. Invertibility & Precision (Round-Trip Recovery)', () => {
    it('perfectly recovers original SUMO coordinates from Three.js coordinates within 1e-9 tolerance', () => {
      const testCases = [
        { x: 2185.00, y: 3540.00, z: 0.0, elev: 0.0 },
        { x: 2105.20, y: 3665.50, z: 0.0, elev: 0.0 },   // J1
        { x: 2186.13, y: 3523.88, z: 0.0, elev: 8.0 },   // J2 with flyover
        { x: 2264.63, y: 3407.70, z: 0.0, elev: -4.5 },  // J3 with underpass
        { x: 1955.72, y: 3887.18, z: 0.0, elev: -4.5 },  // Madiwala
        { x: 2599.63, y: 2862.72, z: 0.0, elev: 7.5 },   // Hosur bypass
      ];

      for (const tc of testCases) {
        const transformed = sumoToThreeCoords(tc.x, tc.y, tc.z, tc.elev);
        const recovered = threeToSumoCoords(transformed.x, transformed.y, transformed.z, tc.elev);

        assert.ok(Math.abs(recovered.x - tc.x) < 1e-9, `X recovery failed for ${JSON.stringify(tc)}`);
        assert.ok(Math.abs(recovered.y - tc.y) < 1e-9, `Y recovery failed for ${JSON.stringify(tc)}`);
        assert.ok(Math.abs(recovered.z - tc.z) < 1e-9, `Z recovery failed for ${JSON.stringify(tc)}`);
      }
    });

    it('round-trips point arrays via transformPoint and inverseTransformPoint', () => {
      const origPt = [2105.20, 3665.50, 0.0];
      const threePt = transformPoint(origPt, 7.50);
      const backPt = inverseTransformPoint(threePt, 7.50);

      assert.ok(Math.abs(backPt[0] - origPt[0]) < 1e-9);
      assert.ok(Math.abs(backPt[1] - origPt[1]) < 1e-9);
      assert.ok(Math.abs(backPt[2] - origPt[2]) < 1e-9);
    });
  });

  describe('3. Cardinal Directions & World Axis Mapping', () => {
    it('North (0 deg SUMO) maps to direction (0, 0, -1) and Euler yaw +PI', () => {
      const dir = sumoHeadingToThreeDirection(0.0);
      assert.ok(Math.abs(dir.x - 0.0) < 1e-9);
      assert.ok(Math.abs(dir.y - 0.0) < 1e-9);
      assert.ok(Math.abs(dir.z - (-1.0)) < 1e-9);

      const yaw = sumoHeadingToThreeYaw(0.0);
      assert.ok(Math.abs(yaw - Math.PI) < 1e-9 || Math.abs(yaw - (-Math.PI)) < 1e-9);

      const recoveredDeg = threeYawToSumoHeading(yaw);
      assert.ok(Math.abs(recoveredDeg - 0.0) < 1e-9 || Math.abs(recoveredDeg - 360.0) < 1e-9);
    });

    it('East (90 deg SUMO) maps to direction (1, 0, 0) and Euler yaw +PI/2', () => {
      const dir = sumoHeadingToThreeDirection(90.0);
      assert.ok(Math.abs(dir.x - 1.0) < 1e-9);
      assert.ok(Math.abs(dir.y - 0.0) < 1e-9);
      assert.ok(Math.abs(dir.z - 0.0) < 1e-9);

      const yaw = sumoHeadingToThreeYaw(90.0);
      assert.ok(Math.abs(yaw - Math.PI / 2) < 1e-9);

      const recoveredDeg = threeYawToSumoHeading(yaw);
      assert.ok(Math.abs(recoveredDeg - 90.0) < 1e-9);
    });

    it('South (180 deg SUMO) maps to direction (0, 0, 1) and Euler yaw 0.0', () => {
      const dir = sumoHeadingToThreeDirection(180.0);
      assert.ok(Math.abs(dir.x - 0.0) < 1e-9);
      assert.ok(Math.abs(dir.y - 0.0) < 1e-9);
      assert.ok(Math.abs(dir.z - 1.0) < 1e-9);

      const yaw = sumoHeadingToThreeYaw(180.0);
      assert.ok(Math.abs(yaw - 0.0) < 1e-9);

      const recoveredDeg = threeYawToSumoHeading(yaw);
      assert.ok(Math.abs(recoveredDeg - 180.0) < 1e-9);
    });

    it('West (270 deg SUMO) maps to direction (-1, 0, 0) and Euler yaw -PI/2', () => {
      const dir = sumoHeadingToThreeDirection(270.0);
      assert.ok(Math.abs(dir.x - (-1.0)) < 1e-9);
      assert.ok(Math.abs(dir.y - 0.0) < 1e-9);
      assert.ok(Math.abs(dir.z - 0.0) < 1e-9);

      const yaw = sumoHeadingToThreeYaw(270.0);
      assert.ok(Math.abs(yaw - (-Math.PI / 2)) < 1e-9);

      const recoveredDeg = threeYawToSumoHeading(yaw);
      assert.ok(Math.abs(recoveredDeg - 270.0) < 1e-9);
    });
  });

  describe('4. Vehicle Heading, Model Orientation & Curved Roads', () => {
    it('applies model-specific offsets when asset is not authored facing canonical +Z', () => {
      // Heading East (90 deg SUMO)
      // Canonical (+Z): yaw = +PI/2
      const canonicalYaw = sumoHeadingToThreeYaw(90.0, MODEL_ORIENTATION_OFFSETS.CANONICAL_Z_FORWARD);
      assert.ok(Math.abs(canonicalYaw - Math.PI / 2) < 1e-9);

      // Camera convention (-Z): yaw = +PI/2 + PI = -PI/2
      const cameraYaw = sumoHeadingToThreeYaw(90.0, MODEL_ORIENTATION_OFFSETS.CAMERA_CONVENTION_MINUS_Z);
      assert.ok(Math.abs(cameraYaw - (-Math.PI / 2)) < 1e-9);

      // CAD convention (+X): yaw = +PI/2 - PI/2 = 0.0
      const cadYaw = sumoHeadingToThreeYaw(90.0, MODEL_ORIENTATION_OFFSETS.CAD_THREEJS_X_FORWARD);
      assert.ok(Math.abs(cadYaw - 0.0) < 1e-9);
    });

    it('correctly maps curved rotary trajectory at J2 Central Silk Board (125.4 deg)', () => {
      const heading = 125.4;
      const dir = sumoHeadingToThreeDirection(heading);
      // sin(125.4) = 0.8151, -cos(125.4) = 0.5793
      assert.ok(Math.abs(dir.x - 0.815126) < 1e-4);
      assert.ok(Math.abs(dir.z - 0.579281) < 1e-4);

      const yaw = sumoHeadingToThreeYaw(heading);
      // PI - 125.4*PI/180 = 0.95295 rad (54.6 deg)
      assert.ok(Math.abs(yaw - 0.95295) < 1e-4);

      const recovered = threeYawToSumoHeading(yaw);
      assert.ok(Math.abs(recovered - heading) < 1e-4);
    });

    it('correctly maps J1 approach curve heading (154.2 deg)', () => {
      const heading = 154.2;
      const dir = sumoHeadingToThreeDirection(heading);
      assert.ok(Math.abs(dir.x - 0.435231) < 1e-4);
      assert.ok(Math.abs(dir.z - 0.900319) < 1e-4);

      const yaw = sumoHeadingToThreeYaw(heading);
      // PI - 154.2*PI/180 = 0.45029 rad (25.8 deg)
      assert.ok(Math.abs(yaw - 0.45029) < 1e-4);

      const recovered = threeYawToSumoHeading(yaw);
      assert.ok(Math.abs(recovered - heading) < 1e-4);
    });

    it('always produces normalized yaw in interval [-PI, +PI]', () => {
      for (let deg = -720; deg <= 720; deg += 15) {
        const yaw = sumoHeadingToThreeYaw(deg);
        assert.ok(yaw >= -Math.PI - 1e-9 && yaw <= Math.PI + 1e-9, `Yaw ${yaw} out of bounds for deg ${deg}`);
      }
    });
  });

  describe('5. Junction Relative Positions & Cardinal Layout', () => {
    it('verifies J1 is North-West of J2, and J3 is South-East of J2 in Three.js space', () => {
      const j1 = corridorData.junctions[corridorData.keyJunctions.J1.id];
      const j2 = corridorData.junctions[corridorData.keyJunctions.J2.id];
      const j3 = corridorData.junctions[corridorData.keyJunctions.J3.id];

      const t1 = sumoToThreeCoords(j1.x, j1.y);
      const t2 = sumoToThreeCoords(j2.x, j2.y);
      const t3 = sumoToThreeCoords(j3.x, j3.y);

      // In Three.js: -Z is North, +Z is South, -X is West, +X is East
      // J1 is North of J2 -> t1.z < t2.z
      assert.ok(t1.z < t2.z, `J1 Z (${t1.z}) should be North of J2 Z (${t2.z})`);
      // J1 is West of J2 -> t1.x < t2.x
      assert.ok(t1.x < t2.x, `J1 X (${t1.x}) should be West of J2 X (${t2.x})`);

      // J3 is South of J2 -> t3.z > t2.z
      assert.ok(t3.z > t2.z, `J3 Z (${t3.z}) should be South of J2 Z (${t2.z})`);
      // J3 is East of J2 -> t3.x > t2.x
      assert.ok(t3.x > t2.x, `J3 X (${t3.x}) should be East of J2 X (${t2.x})`);
    });

    it('transforms junction polygon boundaries into closed 3D loops without vertex corruption', () => {
      const j2 = corridorData.junctions[corridorData.keyJunctions.J2.id];
      assert.ok(j2.shape.length >= 10);

      const threeShape = transformJunctionShape(j2.shape);
      assert.strictEqual(threeShape.length, j2.shape.length);

      for (let i = 0; i < j2.shape.length; i++) {
        const sumoPt = j2.shape[i];
        const threePt = threeShape[i];

        assert.ok(Math.abs(threePt[0] - (sumoPt[0] - DEFAULT_SCENE_ANCHOR.sumo_x)) < 1e-9);
        assert.strictEqual(threePt[1], 0.0);
        assert.ok(Math.abs(threePt[2] - (DEFAULT_SCENE_ANCHOR.sumo_y - sumoPt[1])) < 1e-9);
      }
    });
  });

  describe('6. Isometric Distance Preservation (No Scaling, Distortion or Mirroring)', () => {
    it('preserves Euclidean distances between all three junctions exactly', () => {
      const j1 = corridorData.junctions[corridorData.keyJunctions.J1.id];
      const j2 = corridorData.junctions[corridorData.keyJunctions.J2.id];
      const j3 = corridorData.junctions[corridorData.keyJunctions.J3.id];

      const distSumo_1_2 = computeDistance(j1, j2, 'xy');
      const distSumo_2_3 = computeDistance(j2, j3, 'xy');
      const distSumo_1_3 = computeDistance(j1, j3, 'xy');

      const t1 = sumoToThreeCoords(j1.x, j1.y);
      const t2 = sumoToThreeCoords(j2.x, j2.y);
      const t3 = sumoToThreeCoords(j3.x, j3.y);

      const distThree_1_2 = computeDistance(t1, t2, 'xz');
      const distThree_2_3 = computeDistance(t2, t3, 'xz');
      const distThree_1_3 = computeDistance(t1, t3, 'xz');

      assert.ok(Math.abs(distSumo_1_2 - distThree_1_2) < 1e-9);
      assert.ok(Math.abs(distSumo_2_3 - distThree_2_3) < 1e-9);
      assert.ok(Math.abs(distSumo_1_3 - distThree_1_3) < 1e-9);

      // Verify physical corridor distances:
      // J1 to J2 is ~163.11 meters
      assert.ok(Math.abs(distThree_1_2 - 163.11) < 0.1, `distThree_1_2: ${distThree_1_2}`);
      // J2 to J3 is ~140.21 meters
      assert.ok(Math.abs(distThree_2_3 - 140.21) < 0.1, `distThree_2_3: ${distThree_2_3}`);
      // J1 to J3 is ~303.12 meters
      assert.ok(Math.abs(distThree_1_3 - 303.12) < 0.1, `distThree_1_3: ${distThree_1_3}`);
    });
  });

  describe('7. Representative Road Geometry Validation', () => {
    const representativeEdges = [
      { id: '172853382#3', role: 'J1-J2 Arterial Link', elev: 0.0 },
      { id: '1148717038#0', role: 'J2-J3 Arterial Link', elev: 0.0 },
      { id: '1453814098#0', role: 'Eastbound ORR Link', elev: 0.0 },
      { id: '239438610#0', role: 'Westbound ORR Link', elev: 0.0 },
      { id: '1208112303', role: 'Silk Board Central Flyover (Hosur Bypass)', elev: 7.50 },
      { id: '133763758', role: 'Madiwala Underpass', elev: -4.50 },
    ];

    for (const rep of representativeEdges) {
      it(`validates ${rep.role} (Edge ${rep.id}) preserves point order and distances`, () => {
        const edge = corridorData.edges[rep.id];
        assert.ok(edge, `Edge ${rep.id} missing from corridor data`);

        const lane0 = edge.lanes[0];
        assert.ok(lane0.shape.length >= 2, `Lane shape has fewer than 2 points`);

        const threeLane = transformLaneShape(lane0.shape, rep.elev);
        assert.strictEqual(threeLane.length, lane0.shape.length);

        // Check each point and segment length
        for (let i = 0; i < lane0.shape.length - 1; i++) {
          const s0 = lane0.shape[i];
          const s1 = lane0.shape[i + 1];
          const t0 = threeLane[i];
          const t1 = threeLane[i + 1];

          // Elevation applied to Y
          assert.strictEqual(t0[1], rep.elev);
          assert.strictEqual(t1[1], rep.elev);

          // Distance between consecutive points must be identical
          const sumoSegLen = Math.hypot(s1[0] - s0[0], s1[1] - s0[1]);
          const threeSegLen = Math.hypot(t1[0] - t0[0], t1[2] - t0[2]);
          assert.ok(Math.abs(sumoSegLen - threeSegLen) < 1e-9);
        }
      });
    }
  });

  describe('8. Input Validation & Error Handling', () => {
    it('throws TypeError on non-numeric or NaN coordinates', () => {
      assert.throws(() => sumoToThreeCoords('2185', 3540), TypeError);
      assert.throws(() => sumoToThreeCoords(2185, NaN), TypeError);
      assert.throws(() => sumoToThreeCoords(null, 3540), TypeError);
      assert.throws(() => sumoToThreeCoords(undefined, 3540), TypeError);

      assert.throws(() => threeToSumoCoords(NaN, 0, 0), TypeError);
      assert.throws(() => sumoHeadingToThreeYaw('90'), TypeError);
      assert.throws(() => threeYawToSumoHeading(NaN), TypeError);
    });

    it('throws TypeError on malformed point or shape arrays', () => {
      assert.throws(() => transformPoint([2185]), TypeError);
      assert.throws(() => transformPoint('not-an-array'), TypeError);
      assert.throws(() => transformLaneShape(null), TypeError);
      assert.throws(() => transformJunctionShape({}), TypeError);
    });
  });

});
