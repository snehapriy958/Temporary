import xml.etree.ElementTree as ET
import math

tree = ET.parse('sumo/silk_board/network/silk_board.net.xml')
root = tree.getroot()

edge = root.find("./edge[@id='172853382#3']")
lanes = edge.findall('lane')
shape0 = [list(map(float, p.split(','))) for p in lanes[0].get('shape').split()]
shape1 = [list(map(float, p.split(','))) for p in lanes[1].get('shape').split()]

print('Lane 0 start:', shape0[0])
print('Lane 1 start:', shape1[0])

dx = shape1[0][0] - shape0[0][0]
dy = shape1[0][1] - shape0[0][1]
dist = math.sqrt(dx**2 + dy**2)
print(f'Distance between parallel lane centerlines on 172853382#3: {dist:.4f} meters')

for eid in ['464465165#0', '1208112303', '519734960', '40696222', '1148717038#0']:
    e = root.find(f"./edge[@id='{eid}']")
    if e is not None:
        ls = e.findall('lane')
        if len(ls) >= 2:
            s0 = [list(map(float, p.split(','))) for p in ls[0].get('shape').split()]
            s1 = [list(map(float, p.split(','))) for p in ls[1].get('shape').split()]
            d = math.hypot(s1[0][0] - s0[0][0], s1[0][1] - s0[0][1])
            print(f'Edge {eid:15} parallel lane spacing: {d:.4f} meters')
