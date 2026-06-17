from __future__ import annotations
import math
import random
from typing import Any, List, Dict
import structlog
from app.layouts.topology import LayoutStrategy, TopologyDescriptor
from app.world_model.schemas import WorldModel
from app.scene_graph.schemas import SceneEntity, SceneRelationship, SceneAnnotation
from app.layouts.spatial_region_manager import Rect
from app.dsl.primitives import DSLInstruction

logger = structlog.get_logger(__name__)

def _organic_wobble(
    path: list,
    rng_: random.Random,
    px: float = 2.0,
) -> list:
    """
    Smooth correlated perpendicular wobble — simulates a real hand.

    Unlike pure per-point random jitter, the noise is:
    - Perpendicular to the stroke direction at each point (hand shakes
      sideways, not along the stroke)
    - Correlated between adjacent points (random walk with decay) so
      the line looks organically wavy rather than randomly spiky
    """
    if len(path) < 2 or px < 0.1:
        return path
    result: list = []
    noise = 0.0
    n = len(path)
    for i, pt in enumerate(path):
        x, y = float(pt[0]), float(pt[1])
        if i < n - 1:
            dx, dy = float(path[i + 1][0]) - x, float(path[i + 1][1]) - y
        else:
            dx, dy = x - float(path[i - 1][0]), y - float(path[i - 1][1])
        seg_len = math.sqrt(dx * dx + dy * dy) or 1.0
        perp_x, perp_y = -dy / seg_len, dx / seg_len
        # Correlated random walk toward zero
        noise = noise * 0.82 + (rng_.random() - 0.5) * px * 0.55
        result.append([x + perp_x * noise, y + perp_y * noise])
    return result


def _densify_path(
    path: list,
    min_points: int = 40,
    pixels_per_point: float = 4.0,
) -> list:
    if not path or len(path) < 2:
        return [list(p) for p in path]

    pts = [[float(p[0]), float(p[1])] for p in path]

    arc_length = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        arc_length += math.sqrt(dx * dx + dy * dy)

    target = max(min_points, int(arc_length / pixels_per_point) + 1)
    if len(pts) >= target:
        return pts

    # Closed-loop detection: if the path returns to its start it's a silhouette
    # (apple, organ, leaf outline). Use wrap-around neighbours for the Catmull-Rom
    # tangents so the seam where the contour rejoins itself stays C1-smooth instead
    # of forming a visible corner/flat spot from duplicated endpoints.
    is_closed = (
        len(pts) >= 4
        and abs(pts[0][0] - pts[-1][0]) < 1e-6
        and abs(pts[0][1] - pts[-1][1]) < 1e-6
    )
    if is_closed:
        padded = [pts[-2]] + pts + [pts[1]]
    else:
        padded = [pts[0]] + pts + [pts[-1]]
    result = []
    n_segs = len(pts) - 1
    pps = max(2, target // max(1, n_segs))

    for seg in range(n_segs):
        p0, p1, p2, p3 = padded[seg], padded[seg+1], padded[seg+2], padded[seg+3]
        count = pps if seg < n_segs - 1 else pps + 1
        for k in range(count):
            t  = k / pps
            t2 = t * t; t3 = t2 * t
            x  = 0.5 * ((2*p1[0]) + (-p0[0]+p2[0])*t + (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 + (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y  = 0.5 * ((2*p1[1]) + (-p0[1]+p2[1])*t + (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 + (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            result.append([x, y])

    if result and (result[-1][0] != pts[-1][0] or result[-1][1] != pts[-1][1]):
        result.append(list(pts[-1]))
    return result


class RegionalLayoutStrategy(LayoutStrategy):
    """Layout strategy for region-bounded procedural sketching and zoning allocations."""

    _STROKE_MIN_PTS = 60
    _RECT_MIN_PTS   = 80
    _ARROW_MIN_PTS  = 50

    def __init__(self) -> None:
        self._region_cache: dict[tuple[int, str], Rect] = {}

    def layout(
        self,
        world_model: WorldModel | DSLInstruction,
        descriptor: TopologyDescriptor,
        flow_layout: Any,
        region_mgr: Any
    ) -> List[Any]:
        """Layout procedural sketches and regional items."""
        if isinstance(world_model, DSLInstruction):
            from app.world_model.adapter import LegacyAdapter
            world_model = LegacyAdapter.adapt(world_model)

        entities = world_model.entities
        if not entities:
            return []
            
        entity = entities[0]
        sketch_id = entity.id
        shapes_data = entity.metadata.get("shapes", [])

        # Check if we already have an allocated region for this sketch on the current page
        page_index = flow_layout.scene_index
        cache_key = (page_index, sketch_id)
        
        if cache_key in self._region_cache:
            region_rect = self._region_cache[cache_key]
        else:
            # Allocate a SQUARE, centered drawing box. Normalized [0,1] sketch
            # coordinates assume a square canvas, so a square region maps x and y
            # at the same pixels-per-unit — a circle stays round and an apple keeps
            # its real proportions instead of being stretched across a wide strip.
            side = flow_layout.estimate_diagram_height(diagram_type="sketch")
            side = min(side, flow_layout.content_width)
            pos = flow_layout.place(side, side, align="center", gap_after=60)
            region_rect = Rect(pos.x, pos.y, side, side)
            self._region_cache[cache_key] = region_rect

        return self._resolve_sketch_shapes(sketch_id, shapes_data, region_rect)

    def _resolve_sketch_shapes(
        self,
        sketch_id: str,
        shapes_data: List[Dict[str, Any]],
        region: Rect,
    ) -> List[Any]:
        # Render-and-check loop: sanitize and auto-frame the LLM's blind geometry
        # in normalized space BEFORE mapping to pixels. Drops degenerate shapes,
        # clamps off-canvas coords, and re-frames a tiny/off-centre figure to fill
        # the region — a deterministic guarantee that works on any tier without an
        # LLM re-draw. See app/verification/sketch_verifier.py.
        from app.verification.sketch_verifier import verify_and_repair_shapes
        shapes_data, _ = verify_and_repair_shapes(shapes_data, sketch_id=sketch_id)

        scene_elements = []
        rng = random.Random(hash(sketch_id) & 0x7FFFFFFF)

        def resolve_coord(pt: Any) -> tuple[float, float]:
            if isinstance(pt, dict):
                x = region.x + pt.get("x_pct", 0.5) * region.width  if "x_pct" in pt else region.x + pt.get("x", 0)
                y = region.y + pt.get("y_pct", 0.5) * region.height if "y_pct" in pt else region.y + pt.get("y", 0)
                return x, y
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                px, py = float(pt[0]), float(pt[1])
                if 0 <= px <= 1.0 and 0 <= py <= 1.0:
                    return region.x + px * region.width, region.y + py * region.height
                return region.x + px, region.y + py
            return region.center_x, region.center_y

        for idx, shape_def in enumerate(shapes_data):
            stype     = shape_def.get("type", "").lower()
            color     = shape_def.get("color", "#FFFFFF")
            # 4.0px default: diagram shapes must be clearly visible on the whiteboard.
            # Labels keep their own default (smaller); all other shapes use this floor.
            thickness = shape_def.get("thickness", 2.0 if stype == "label" else 4.0)
            shape_id  = shape_def.get("id", f"{sketch_id}_s_{idx}")

            if stype == "circle":
                cx, cy   = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                r        = shape_def.get("radius", 50)
                if isinstance(r, float) and 0 < r <= 1.0:
                    r = r * min(region.width, region.height)
                waviness = shape_def.get("waviness", 0.0)
                seg      = 48
                path     = []
                for i in range(seg + 1):
                    a   = (i / seg) * 2 * math.pi
                    wob = math.sin(a * 6) * waviness * r if waviness else 0
                    ji  = (rng.random() - 0.5) * 2.5
                    cr  = r + wob + ji
                    path.append([cx + cr * math.cos(a), cy + cr * math.sin(a)])
                path  = _organic_wobble(path, rng, 2.0)
                dense = _densify_path(path, self._STROKE_MIN_PTS, 4.0)
                
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - r,
                    y=cy - r,
                    width=r * 2,
                    height=r * 2,
                    semantic_role="circle",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype == "blob":
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                rx = shape_def.get("rx", 60); ry = shape_def.get("ry", 40)
                if isinstance(rx, float) and 0 < rx <= 1.0: rx = rx * region.width
                if isinstance(ry, float) and 0 < ry <= 1.0: ry = ry * region.height
                waviness = shape_def.get("waviness", 0.15)
                seg      = 48
                path     = []
                for i in range(seg + 1):
                    a   = (i / seg) * 2 * math.pi
                    wob = (math.sin(a*5)*0.6 + math.cos(a*3)*0.4) * waviness * min(rx, ry)
                    ji  = (rng.random() - 0.5) * 2.5
                    path.append([cx + (rx+wob+ji)*math.cos(a), cy + (ry+wob+ji)*math.sin(a)])
                path  = _organic_wobble(path, rng, 2.2)
                dense = _densify_path(path, self._STROKE_MIN_PTS, 4.0)
                
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - rx,
                    y=cy - ry,
                    width=rx * 2,
                    height=ry * 2,
                    semantic_role="blob",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype in ("rect", "rectangle"):
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                w = shape_def.get("width", 100); h_ = shape_def.get("height", 80)
                if isinstance(w, float) and 0 < w <= 1.0: w = w * region.width
                if isinstance(h_, float) and 0 < h_ <= 1.0: h_ = h_ * region.height
                pps  = max(15, int(max(w, h_) / 4))
                def side(x1, y1, x2, y2, n=pps):
                    return [[x1+(x2-x1)*i/n+(rng.random()-0.5)*0.8,
                             y1+(y2-y1)*i/n+(rng.random()-0.5)*0.8] for i in range(n)]
                xl, xr = cx-w/2, cx+w/2; yt, yb = cy-h_/2, cy+h_/2
                path  = side(xl,yt,xr,yt)+side(xr,yt,xr,yb)+side(xr,yb,xl,yb)+side(xl,yb,xl,yt)+[[xl,yt]]
                dense = _densify_path(path, self._RECT_MIN_PTS, 4.0)
                
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=xl,
                    y=yt,
                    width=w,
                    height=h_,
                    semantic_role="rectangle",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype in ("line", "wavy_line"):
                x1, y1 = resolve_coord(shape_def.get("start", [0.2, 0.5]))
                x2, y2 = resolve_coord(shape_def.get("end",   [0.8, 0.5]))
                dx, dy = x2-x1, y2-y1
                length = math.sqrt(dx*dx + dy*dy)
                if stype == "wavy_line":
                    seg = max(20, int(length/10)); amp = shape_def.get("amplitude", 4.0)
                    ox = -dy/length if length else 0; oy = dx/length if length else 0
                    path = [[x1+t/seg*dx + ox*math.sin(t/seg*math.pi*4)*amp,
                             y1+t/seg*dy + oy*math.sin(t/seg*math.pi*4)*amp] for t in range(seg+1)]
                else:
                    seg  = max(self._STROKE_MIN_PTS, int(length/4))
                    path = [[x1+t/seg*dx+(rng.random()-0.5)*1.0,
                             y1+t/seg*dy+(rng.random()-0.5)*1.0] for t in range(seg+1)]
                dense = _densify_path(path, self._STROKE_MIN_PTS, 4.0)
                
                scene_elements.append(SceneRelationship(
                    id=shape_id,
                    source_id="start",
                    target_id="end",
                    x=min(x1, x2),
                    y=min(y1, y2),
                    width=abs(dx),
                    height=abs(dy),
                    relation_type="stroke_line",
                    semantic_role="line",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype == "arrow":
                x1, y1 = resolve_coord(shape_def.get("start", [0.2, 0.5]))
                x2, y2 = resolve_coord(shape_def.get("end",   [0.8, 0.5]))
                dx, dy = x2-x1, y2-y1; length = math.sqrt(dx*dx+dy*dy)
                if length > 0:
                    mx,my = (x1+x2)/2,(y1+y2)/2
                    ox,oy = -dy/length, dx/length
                    bend  = length * shape_def.get("bend", 0.08)
                    bx,by = mx+ox*bend, my+oy*bend
                    n_pts = max(self._ARROW_MIN_PTS, int(length/4))
                    shaft = [[((1-t)**2)*x1+2*(1-t)*t*bx+t**2*x2,
                              ((1-t)**2)*y1+2*(1-t)*t*by+t**2*y2]
                             for t in [i/n_pts for i in range(n_pts+1)]]
                    theta = math.atan2(y2-by, x2-bx); hl = shape_def.get("head_len", 14.0)
                    ha    = math.pi/6.0
                    tl = [x2-hl*math.cos(theta-ha), y2-hl*math.sin(theta-ha)]
                    tr = [x2-hl*math.cos(theta+ha), y2-hl*math.sin(theta+ha)]
                    ds = _densify_path(shaft, self._ARROW_MIN_PTS, 4.0)
                    tip = _densify_path([tl,[x2,y2],tr], min_points=20, pixels_per_point=3.0)
                    
                    scene_elements.append(SceneRelationship(
                        id=shape_id,
                        source_id="start",
                        target_id="end",
                        x=min(x1, x2),
                        y=min(y1, y2),
                        width=abs(dx),
                        height=abs(dy),
                        relation_type="stroke_arrow",
                        semantic_role="arrow",
                        properties={
                            "path": ds,
                            "tip_path": tip,
                            "color": color,
                            "thickness": thickness
                        }
                    ))

            elif stype == "ellipse":
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                rx = shape_def.get("rx", 60); ry = shape_def.get("ry", 40)
                if isinstance(rx, float) and 0 < rx <= 1.0: rx = rx * region.width
                if isinstance(ry, float) and 0 < ry <= 1.0: ry = ry * region.height
                rot = math.radians(shape_def.get("rotation", 0))
                seg = 48
                path = []
                for i in range(seg + 1):
                    a = (i / seg) * 2 * math.pi
                    ex, ey = rx * math.cos(a), ry * math.sin(a)
                    ji = (rng.random() - 0.5) * 2.0
                    px = cx + ex * math.cos(rot) - ey * math.sin(rot) + ji
                    py = cy + ex * math.sin(rot) + ey * math.cos(rot) + (rng.random() - 0.5) * 2.0
                    path.append([px, py])
                path  = _organic_wobble(path, rng, 1.8)
                dense = _densify_path(path, self._STROKE_MIN_PTS, 4.0)
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - rx,
                    y=cy - ry,
                    width=rx * 2,
                    height=ry * 2,
                    semantic_role="ellipse",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))
                
            elif stype == "triangle":
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                w = shape_def.get("width", 100); h_ = shape_def.get("height", 80)
                if isinstance(w, float) and 0 < w <= 1.0: w = w * region.width
                if isinstance(h_, float) and 0 < h_ <= 1.0: h_ = h_ * region.height
                v0 = [cx, cy - h_/2]
                v1 = [cx + w/2, cy + h_/2]
                v2 = [cx - w/2, cy + h_/2]
                pps = max(15, int(max(w, h_) / 4))
                def side(x1, y1, x2, y2, n=pps):
                    return [[x1+(x2-x1)*i/n+(rng.random()-0.5)*0.8,
                             y1+(y2-y1)*i/n+(rng.random()-0.5)*0.8] for i in range(n)]
                path = side(v0[0], v0[1], v1[0], v1[1], pps) + \
                       side(v1[0], v1[1], v2[0], v2[1], pps) + \
                       side(v2[0], v2[1], v0[0], v0[1], pps) + [v0]
                dense = _densify_path(path, self._RECT_MIN_PTS, 4.0)
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - w/2,
                    y=cy - h_/2,
                    width=w,
                    height=h_,
                    semantic_role="triangle",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype == "diamond":
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                w = shape_def.get("width", 100); h_ = shape_def.get("height", 100)
                if isinstance(w, float) and 0 < w <= 1.0: w = w * region.width
                if isinstance(h_, float) and 0 < h_ <= 1.0: h_ = h_ * region.height
                v0 = [cx, cy - h_/2]
                v1 = [cx + w/2, cy]
                v2 = [cx, cy + h_/2]
                v3 = [cx - w/2, cy]
                pps = max(15, int(max(w, h_) / 4))
                def side(x1, y1, x2, y2, n=pps):
                    return [[x1+(x2-x1)*i/n+(rng.random()-0.5)*0.8,
                             y1+(y2-y1)*i/n+(rng.random()-0.5)*0.8] for i in range(n)]
                path = side(v0[0], v0[1], v1[0], v1[1], pps) + \
                       side(v1[0], v1[1], v2[0], v2[1], pps) + \
                       side(v2[0], v2[1], v3[0], v3[1], pps) + \
                       side(v3[0], v3[1], v0[0], v0[1], pps) + [v0]
                dense = _densify_path(path, self._RECT_MIN_PTS, 4.0)
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - w/2,
                    y=cy - h_/2,
                    width=w,
                    height=h_,
                    semantic_role="diamond",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype == "star":
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                r_outer = shape_def.get("radius") or shape_def.get("r", 50)
                if isinstance(r_outer, float) and 0 < r_outer <= 1.0:
                    r_outer = r_outer * min(region.width, region.height)
                r_inner = r_outer * 0.4
                points_count = 5
                path = []
                for i in range(2 * points_count + 1):
                    angle = i * (math.pi / points_count) - math.pi / 2
                    r = r_outer if i % 2 == 0 else r_inner
                    px = cx + r * math.cos(angle) + (rng.random() - 0.5) * 2.0
                    py = cy + r * math.sin(angle) + (rng.random() - 0.5) * 2.0
                    path.append([px, py])
                path  = _organic_wobble(path, rng, 1.8)
                dense = _densify_path(path, self._RECT_MIN_PTS, 4.0)
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - r_outer,
                    y=cy - r_outer,
                    width=r_outer * 2,
                    height=r_outer * 2,
                    semantic_role="star",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype == "cloud":
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                rx = shape_def.get("rx", 60); ry = shape_def.get("ry", 40)
                if isinstance(rx, float) and 0 < rx <= 1.0: rx = rx * region.width
                if isinstance(ry, float) and 0 < ry <= 1.0: ry = ry * region.height
                seg = 60
                path = []
                for i in range(seg + 1):
                    a = (i / seg) * 2 * math.pi
                    bump = 1.0 + 0.25 * abs(math.sin(a * 5))
                    px = cx + rx * bump * math.cos(a) + (rng.random() - 0.5) * 2.0
                    py = cy + ry * bump * math.sin(a) + (rng.random() - 0.5) * 2.0
                    path.append([px, py])
                path  = _organic_wobble(path, rng, 1.5)
                dense = _densify_path(path, self._STROKE_MIN_PTS, 4.0)
                scene_elements.append(SceneEntity(
                    id=shape_id,
                    label="",
                    x=cx - rx * 1.25,
                    y=cy - ry * 1.25,
                    width=rx * 2.5,
                    height=ry * 2.5,
                    semantic_role="cloud",
                    properties={
                        "path": dense,
                        "color": color,
                        "thickness": thickness
                    }
                ))

            elif stype in ("path", "freeform", "curve", "polyline"):
                raw_pts = shape_def.get("points") or []
                pts = [list(resolve_coord(p)) for p in raw_pts]
                is_closed = bool(shape_def.get("closed")) and len(pts) >= 3
                if len(pts) >= 2:
                    pts   = _organic_wobble(pts, rng, 1.5)
                    # Snap the loop shut AFTER wobble so the silhouette actually
                    # closes — the wobble perturbs each point independently, so a
                    # pre-wobble closing point would leave a seam gap. An exact
                    # duplicate of the first point also lets _densify_path detect
                    # the closed loop and keep the seam C1-smooth.
                    if is_closed:
                        pts.append(list(pts[0]))
                    dense = _densify_path(pts, self._STROKE_MIN_PTS, 4.0)
                    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]

                    scene_elements.append(SceneEntity(
                        id=shape_id,
                        label="",
                        x=min(xs),
                        y=min(ys),
                        width=max(xs) - min(xs),
                        height=max(ys) - min(ys),
                        semantic_role="freeform",
                        properties={
                            "path": dense,
                            "color": color,
                            "thickness": thickness
                        }
                    ))

            elif stype == "arc":
                # Partial circle / ellipse (start_angle → end_angle, degrees).
                # Critical for organic shapes: ears, smiles, hearts, arches.
                cx, cy = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                r       = shape_def.get("radius") or shape_def.get("r", 50)
                if isinstance(r, float) and 0 < r <= 1.0:
                    r = r * min(region.width, region.height)
                rx = shape_def.get("rx", r); ry = shape_def.get("ry", r)
                if isinstance(rx, float) and 0 < rx <= 1.0: rx = rx * region.width
                if isinstance(ry, float) and 0 < ry <= 1.0: ry = ry * region.height
                start_a = math.radians(shape_def.get("start_angle", 0))
                end_a   = math.radians(shape_def.get("end_angle", 180))
                if end_a <= start_a:
                    end_a += 2 * math.pi
                seg  = max(20, int(abs(end_a - start_a) * 24))
                path = []
                for i in range(seg + 1):
                    t = i / seg
                    a = start_a + t * (end_a - start_a)
                    path.append([cx + rx * math.cos(a), cy + ry * math.sin(a)])
                path  = _organic_wobble(path, rng, 2.0)
                dense = _densify_path(path, self._STROKE_MIN_PTS, 4.0)
                xs = [p[0] for p in path]; ys = [p[1] for p in path]
                scene_elements.append(SceneEntity(
                    id=shape_id, label="",
                    x=min(xs), y=min(ys),
                    width=max(xs)-min(xs), height=max(ys)-min(ys),
                    semantic_role="arc",
                    properties={"path": dense, "color": color, "thickness": thickness}
                ))

            elif stype in ("polygon", "ngon"):
                # Arbitrary polygon: either explicit `vertices` list (0-1 normalized)
                # or a regular n-gon via `sides` + `radius`.
                cx, cy    = resolve_coord(shape_def.get("center", [0.5, 0.5]))
                vertices  = shape_def.get("vertices", [])
                if vertices:
                    pts = [list(resolve_coord(v)) for v in vertices]
                else:
                    sides = int(shape_def.get("sides", 6))
                    r_raw = shape_def.get("radius", 50)
                    if isinstance(r_raw, float) and 0 < r_raw <= 1.0:
                        r_raw = r_raw * min(region.width, region.height)
                    rot_off = math.radians(shape_def.get("rotation", 0))
                    pts = [
                        [cx + r_raw * math.cos(rot_off + 2 * math.pi * i / sides),
                         cy + r_raw * math.sin(rot_off + 2 * math.pi * i / sides)]
                        for i in range(sides)
                    ]
                if len(pts) >= 2:
                    pts.append(list(pts[0]))   # close
                    pps  = max(10, int(min(
                        math.sqrt((pts[j+1][0]-pts[j][0])**2 + (pts[j+1][1]-pts[j][1])**2)
                        for j in range(len(pts)-1)
                    ) / 4))
                    path = []
                    for j in range(len(pts) - 1):
                        x1, y1 = pts[j]; x2, y2 = pts[j + 1]
                        for k in range(pps):
                            t = k / pps
                            path.append([x1+(x2-x1)*t + (rng.random()-0.5)*1.5,
                                         y1+(y2-y1)*t + (rng.random()-0.5)*1.5])
                    path.append(list(pts[0]))
                    path  = _organic_wobble(path, rng, 2.0)
                    dense = _densify_path(path, self._RECT_MIN_PTS, 4.0)
                    xs    = [p[0] for p in pts]; ys = [p[1] for p in pts]
                    scene_elements.append(SceneEntity(
                        id=shape_id, label="",
                        x=min(xs), y=min(ys),
                        width=max(xs)-min(xs), height=max(ys)-min(ys),
                        semantic_role="polygon",
                        properties={"path": dense, "color": color, "thickness": thickness}
                    ))

            elif stype == "label":
                cx, cy = resolve_coord(shape_def.get("position", [0.5, 0.5]))
                scene_elements.append(SceneAnnotation(
                    id=shape_id,
                    text=shape_def.get("text", ""),
                    x=cx - 80,
                    y=cy - 20,
                    width=160,
                    height=40,
                    properties={
                        "color": color,
                        "font_size": shape_def.get("font_size", 20),
                        "duration_ms": shape_def.get("duration_ms", 1200)
                    }
                ))

        return scene_elements
