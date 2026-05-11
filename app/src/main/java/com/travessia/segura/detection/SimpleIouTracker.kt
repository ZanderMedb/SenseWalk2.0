package com.travessia.segura.detection

/**
 * Tracker simples baseado em IoU.
 * Associa detecções frame-a-frame por sobreposição de bboxes.
 */
class SimpleIoUTracker(
    private val iouThreshold: Float = 0.25f,
    private val maxAge: Int = 8
) {
    private var nextId = 0

    private data class TrackState(
        var det: RawDetection,
        var age: Int = 0,
        val trackId: Int
    )

    private val tracks = mutableMapOf<Int, TrackState>()

    fun update(detections: List<RawDetection>): List<TrackedDetection> {
        val result = mutableListOf<TrackedDetection>()

        if (tracks.isEmpty()) {
            for (det in detections) {
                val tid = nextId++
                tracks[tid] = TrackState(det, 0, tid)
                result.add(det.toTracked(tid))
            }
            return result
        }

        val matched = mutableSetOf<Int>()
        val matchedDets = mutableSetOf<Int>()

        // Calcular todos os pares (track, detection) com IoU
        val trackIds = tracks.keys.toList()
        val pairs = mutableListOf<Triple<Int, Int, Float>>()

        for (t in trackIds.indices) {
            for (d in detections.indices) {
                val iou = computeIoU(tracks[trackIds[t]]!!.det, detections[d])
                if (iou > iouThreshold) {
                    pairs.add(Triple(t, d, iou))
                }
            }
        }

        // Greedy matching por IoU descendente
        pairs.sortByDescending { it.third }

        for ((t, d, _) in pairs) {
            val tid = trackIds[t]
            if (tid in matched || d in matchedDets) continue

            tracks[tid]!!.det = detections[d]
            tracks[tid]!!.age = 0
            matched.add(tid)
            matchedDets.add(d)
            result.add(detections[d].toTracked(tid))
        }

        // Novas detecções → novos tracks
        for (d in detections.indices) {
            if (d !in matchedDets) {
                val tid = nextId++
                tracks[tid] = TrackState(detections[d], 0, tid)
                result.add(detections[d].toTracked(tid))
            }
        }

        // Tracks não associados → envelhecer ou remover
        val toRemove = mutableListOf<Int>()
        for (tid in trackIds) {
            if (tid !in matched) {
                tracks[tid]!!.age++
                if (tracks[tid]!!.age > maxAge) {
                    toRemove.add(tid)
                }
            }
        }
        toRemove.forEach { tracks.remove(it) }

        return result
    }

    fun reset() {
        tracks.clear()
        nextId = 0
    }

    private fun computeIoU(a: RawDetection, b: RawDetection): Float {
        val ix1 = maxOf(a.x1, b.x1)
        val iy1 = maxOf(a.y1, b.y1)
        val ix2 = minOf(a.x2, b.x2)
        val iy2 = minOf(a.y2, b.y2)
        val inter = (ix2 - ix1).coerceAtLeast(0f) * (iy2 - iy1).coerceAtLeast(0f)
        val areaA = (a.x2 - a.x1) * (a.y2 - a.y1)
        val areaB = (b.x2 - b.x1) * (b.y2 - b.y1)
        val union = areaA + areaB - inter
        return if (union > 0f) inter / union else 0f
    }

    private fun RawDetection.toTracked(trackId: Int) = TrackedDetection(
        trackId = trackId,
        x1 = x1, y1 = y1, x2 = x2, y2 = y2,
        classId = classId,
        className = className,
        confidence = confidence
    )
}