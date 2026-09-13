#pragma once
#include <algorithm>

namespace DlssNr
{
// Rolling GPU-timing samples for the periodic vitals summary (DlssNr_Dx12_Status.cpp). A single
// frame's split (logged every 600 frames before this existed) only ever shows whatever frame
// happened to land on the 600th tick - it can miss every real spike in between. This keeps the
// whole window so the summary reports what actually happened across it, not one arbitrary sample.
//
// 256 slots covers roughly 3-4s at 60-90fps: enough for a stable worst-case (p99) read without the
// memory/sort cost of a much larger window. Adapted from a lock-free ring-buffer/percentile pattern
// already proven in ~/Dev/greenboost_all/greenboost_gaming's Vulkan layer (frame-time P99 -> 1% low
// FPS); this version reports the metric this project already uses - milliseconds of GPU cost, not
// a converted framerate - and uses std::sort over a plain C insertion sort since STL is available
// here and 256 elements is negligible to sort once every few hundred frames.
class DlssNrVitals
{
  public:
    static constexpr unsigned int kSize = 256;

    void Push(double totalMs, double ngxMs)
    {
        const auto i = static_cast<unsigned int>(_head % kSize);
        _total[i] = totalMs;
        _ngx[i] = ngxMs;
        ++_head;
    }

    unsigned int Count() const { return _head < kSize ? static_cast<unsigned int>(_head) : kSize; }

    // p99 here is a TIME (the worst 1% of frames), not a framerate - this is a cost metric, so
    // "worst" means "highest," matching how this file already reports NR cost in milliseconds
    // rather than converting to fps the way a display-facing HUD would.
    struct Summary
    {
        double totalMean = 0.0;
        double totalP99 = 0.0;
        double ngxMean = 0.0;
        double ngxP99 = 0.0;
        unsigned int sampleCount = 0;
    };

    Summary Compute() const
    {
        Summary s {};
        s.sampleCount = Count();
        if (s.sampleCount == 0)
            return s;

        double totalSorted[kSize];
        double ngxSorted[kSize];
        double totalSum = 0.0, ngxSum = 0.0;
        for (unsigned int i = 0; i < s.sampleCount; ++i)
        {
            totalSorted[i] = _total[i];
            ngxSorted[i] = _ngx[i];
            totalSum += _total[i];
            ngxSum += _ngx[i];
        }
        std::sort(totalSorted, totalSorted + s.sampleCount);
        std::sort(ngxSorted, ngxSorted + s.sampleCount);

        const auto idx99 = std::min(s.sampleCount - 1, s.sampleCount * 99u / 100u);
        s.totalMean = totalSum / s.sampleCount;
        s.ngxMean = ngxSum / s.sampleCount;
        s.totalP99 = totalSorted[idx99];
        s.ngxP99 = ngxSorted[idx99];
        return s;
    }

  private:
    double _total[kSize] {};
    double _ngx[kSize] {};
    unsigned long long _head = 0;
};
}
