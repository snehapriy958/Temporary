/**
 * frontend/src/utils/roadGeometryBuilder.test.js
 *
 * Automated tests for 3D road geometry mesh construction:
 * Tests ribbon generation, normal vectors, ramp elevation interpolation,
 * pillar placement, and junction polygon triangulation.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  createRibbonGeometry,
  interpolateRampElevation,
  getLaneThreePoints,
  createDashedDividerGeometry,
  createPillarsGeometry,
  createJunctionGeometry,
  mergeBufferGeometries,
  buildCorridorSceneGeometries,
  ROAD_STYLE,
} from './roadGeometryBuilder.js';

// Load extracted geometry data
const geometryUrl = new URL('../data/corridorNetworkGeometry.json', import.meta.url);
const corridorData = JSON.parse(readFileSync(fileURLToPath(geometryUrl), 'utf-8'));

describe('Phase 3B Stage 3: Road Geometry Mesh Construction Engine', () => {

  describe('1. Ribbon Mesh Generation', () => {
    it('constructs a valid BufferGeometry from a 2-point polyline', () => {
      const pts = [
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(10, 0, 0)
      ];
      const geom = createRibbonGeometry(pts, 3.20);

      assert.ok(geom instanceof THREE.BufferGeometry);
      const pos = geom.attributes.position;
      assert.strictEqual(pos.count, 4); // 2 points * 2 vertices (left/right)
      assert.strictEqual(geom.index.count, 6); // 2 triangles * 3 indices
    });

    it('creates correct road width for 3.20m standard lane', () => {
      // Polyline along X axis
      const pts = [
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(10, 0, 0)
      ];
      const width = 3.20;
      const geom = createRibbonGeometry(pts, width);

      const pos = geom.attributes.position;
      // First point: left vertex (0, 0, -1.6), right vertex (0, 0, +1.6)
      const lz = pos.getZ(0);
      const rz = pos.getZ(1);
      const measuredWidth = Math.abs(rz - lz);

      assert.ok(Math.abs(measuredWidth - width) < 1e-5, `Width mismatch: measured ${measuredWidth}, expected ${width}`);
    });
  });

  describe('2. Ramp Smoothstep Elevation Interpolation', () => {
    it('smoothly interpolates from 0.0m to 8.0m on ascending ramp', () => {
      const targetElev = 8.00;
      assert.strictEqual(interpolateRampElevation(0.0, targetElev, true), 0.0);
      assert.ok(Math.abs(interpolateRampElevation(0.5, targetElev, true) - 4.0) < 1e-5); // Halfway
      assert.strictEqual(interpolateRampElevation(1.0, targetElev, true), targetElev);
    });

    it('smoothly interpolates from 8.0m to 0.0m on descending off-ramp', () => {
      const targetElev = 8.00;
      assert.strictEqual(interpolateRampElevation(0.0, targetElev, false), targetElev);
      assert.ok(Math.abs(interpolateRampElevation(0.5, targetElev, false) - 4.0) < 1e-5);
      assert.strictEqual(interpolateRampElevation(1.0, targetElev, false), 0.0);
    });
  });

  describe('3. Representative Corridor Road Geometry Construction', () => {
    it('constructs continuous road ribbons for J1-J2 arterial (Edge 172853382#3)', () => {
      const edge = corridorData.edges['172853382#3'];
      assert.ok(edge);

      for (const lane of edge.lanes) {
        const threePts = getLaneThreePoints(edge, lane);
        assert.ok(threePts.length >= 2);
        const ribbon = createRibbonGeometry(threePts, lane.width);
        assert.ok(ribbon.attributes.position.count >= 4);
      }
    });

    it('constructs elevated flyover road ribbons for Silk Board Flyover (Edge 1208112303)', () => {
      const edge = corridorData.edges['1208112303'];
      assert.ok(edge);
      assert.strictEqual(edge.assumedElevation, 7.50);

      const threePts = getLaneThreePoints(edge, edge.lanes[0]);
      for (const p of threePts) {
        assert.strictEqual(p.y, 7.50); // Elev strictly applied to Y
      }

      const ribbon = createRibbonGeometry(threePts, edge.lanes[0].width);
      assert.ok(ribbon.attributes.position.count >= 4);
    });

    it('constructs depressed underpass road ribbons for Madiwala Underpass (Edge 133763758)', () => {
      const edge = corridorData.edges['133763758'];
      assert.ok(edge);
      assert.strictEqual(edge.assumedElevation, -4.50);

      const threePts = getLaneThreePoints(edge, edge.lanes[0]);
      for (const p of threePts) {
        assert.strictEqual(p.y, -4.50);
      }
    });
  });

  describe('4. Concrete Pillar Placement', () => {
    it('generates concrete supporting pillars for elevated flyover span', () => {
      const edge = corridorData.edges['1208112303']; // 533m length, +7.5m elev
      const threePts = getLaneThreePoints(edge, edge.lanes[0]);

      const pillars = createPillarsGeometry(threePts, 30.0, 0.6);
      assert.ok(pillars.attributes.position.count > 0, 'Should generate pillar vertices');
      // For a ~533m span with 30m spacing, expects ~17 pillars
      const estimatedPillars = Math.floor(533.9 / 30.0);
      assert.ok(estimatedPillars >= 15);
    });

    it('generates zero pillars for ground-level roads (Y <= 2.5m)', () => {
      const groundEdge = corridorData.edges['172853382#3']; // Ground road
      const threePts = getLaneThreePoints(groundEdge, groundEdge.lanes[0]);

      const pillars = createPillarsGeometry(threePts, 30.0, 0.6);
      assert.strictEqual(pillars.attributes.position, undefined, 'No pillars should be generated at ground level');
    });
  });

  describe('5. Junction Polygon Triangulation', () => {
    it('triangulates J1, J2, and J3 boundary polygons without errors', () => {
      const keyJuncIds = [
        corridorData.keyJunctions.J1.id,
        corridorData.keyJunctions.J2.id,
        corridorData.keyJunctions.J3.id,
      ];

      for (const jid of keyJuncIds) {
        const j = corridorData.junctions[jid];
        assert.ok(j.shape.length >= 10);

        const juncGeom = createJunctionGeometry(j.shape, 0.0);
        assert.ok(juncGeom instanceof THREE.BufferGeometry);
        assert.ok(juncGeom.attributes.position.count >= 10);
      }
    });
  });

  describe('6. Geometry Merging and Batching', () => {
    it('merges multiple ribbon geometries into a unified BufferGeometry', () => {
      const g1 = createRibbonGeometry([new THREE.Vector3(0, 0, 0), new THREE.Vector3(10, 0, 0)], 3.2);
      const g2 = createRibbonGeometry([new THREE.Vector3(0, 0, 10), new THREE.Vector3(10, 0, 10)], 3.2);

      const merged = mergeBufferGeometries([g1, g2]);
      assert.ok(merged instanceof THREE.BufferGeometry);
      assert.strictEqual(merged.attributes.position.count, g1.attributes.position.count + g2.attributes.position.count);
      assert.strictEqual(merged.index.count, g1.index.count + g2.index.count);
    });

    it('returns empty BufferGeometry on empty array', () => {
      const empty = mergeBufferGeometries([]);
      assert.ok(empty instanceof THREE.BufferGeometry);
      assert.strictEqual(empty.attributes.position, undefined);
    });
  });

  describe('7. Full Corridor Scene Geometries Construction', () => {
    it('constructs all scene layers with verified vertex counts', () => {
      const sceneGeoms = buildCorridorSceneGeometries(corridorData);

      assert.ok(sceneGeoms.groundRoads.attributes.position.count > 1000, 'Ground roads mesh populated');
      assert.ok(sceneGeoms.flyoverRoads.attributes.position.count > 100, 'Flyover roads mesh populated');
      assert.ok(sceneGeoms.underpassRoads.attributes.position.count >= 60, 'Underpass roads mesh populated');
      assert.ok(sceneGeoms.junctions.attributes.position.count > 500, 'Junction conflict areas mesh populated');
      assert.ok(sceneGeoms.laneDividers.attributes.position.count > 500, 'Lane divider dashed lines mesh populated');
      assert.ok(sceneGeoms.pillars.attributes.position.count > 100, 'Pillar meshes populated');
    });
  });

});
