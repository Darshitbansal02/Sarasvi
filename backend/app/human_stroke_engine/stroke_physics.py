import random
import math
from typing import List, Tuple, Dict, Any

class StrokePhysicsEngine:
    @staticmethod
    def simulate_hesitation(points: List[Tuple[float, float]], target_index: int, amount: float = 2.0) -> List[Tuple[float, float]]:
        """
        Simulates hesitation or thought pauses by adding a micro-tremor/wobble 
        around a specific node index.
        """
        output = list(points)
        n = len(points)
        if n < 3:
            return output
            
        rng = random.Random(target_index)
        # Apply local tremor around target index
        start = max(1, target_index - 3)
        end = min(n - 1, target_index + 4)
        for i in range(start, end):
            d = (1.0 - abs(i - target_index) / 4.0)
            wobble_x = (rng.random() - 0.5) * amount * d
            wobble_y = (rng.random() - 0.5) * amount * d
            output[i] = (output[i][0] + wobble_x, output[i][1] + wobble_y)
            
        return output

    @staticmethod
    def segment_overdraw(points: List[Tuple[float, float]]) -> List[List[Tuple[float, float]]]:
        """
        Simulates teacher corrections and overdrawing by segmenting one single stroke
        into multiple overlapping paths representing outline corrections.
        """
        n = len(points)
        if n < 15:
            return [points]

        # Split into two overlapping segments at roughly 65% of the path
        split_idx = int(n * 0.65)
        overlap = 3
        
        seg1 = points[:split_idx + overlap]
        seg2 = points[split_idx:]
        
        # Add slight overshoot/offset to simulate lifting the pen and correcting outline
        rng = random.Random(42)
        offset_x = (rng.random() - 0.5) * 1.5
        offset_y = (rng.random() - 0.5) * 1.5
        
        seg2_deformed = [(pt[0] + offset_x, pt[1] + offset_y) for pt in seg2]
        
        return [seg1, seg2_deformed]
