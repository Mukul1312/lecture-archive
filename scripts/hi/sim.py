import random
random.seed(0)
def lid_total_and_ggs(intervals, win=30.0):
    ggs = sum(e-s for s,e in intervals)
    lid = 0.0
    for s,e in intervals:
        t=s
        while t < e-1.0:
            w0,w1 = t, min(t+win,e)
            dur=w1-w0
            t=w1
            if dur<2.0: continue
            lid += dur
    return ggs, lid

for mean_turn in (3, 6, 12, 25, 50):
    intervals=[]
    tcur=0.0
    for _ in range(400):
        d = max(0.5, random.expovariate(1.0/mean_turn))
        intervals.append((tcur, tcur+d))
        tcur += d + random.uniform(0.3, 3.0)
    ggs, lid = lid_total_and_ggs(intervals)
    print(f"mean_turn={mean_turn:5.1f}s  ggs={ggs/60:6.1f}min  lid'd={lid/60:6.1f}min  coverage={100*lid/ggs:5.1f}%  UN-LID'd={100*(ggs-lid)/ggs:4.1f}%")
