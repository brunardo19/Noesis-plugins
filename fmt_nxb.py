from inc_noesis import *

def registerNoesisTypes():
    handle = noesis.register("Battle Fantasia -Revised-", ".nxb")
    noesis.logPopup()
    noesis.setHandlerTypeCheck(handle, noepyCheckType)
    noesis.setHandlerLoadModel(handle, noepyLoadModel)
    return 1

def noepyCheckType(data):
    if data.find(b'VRTB') == -1:
        return 0
    return 1

def loadNXB(bs, mdlList):
    bs = NoeBitStream(bs)
    form_offset = [(i+4) for i in findall(b'FORM', bs)]
    for x in range(len(form_offset)):
        bs.seek(form_offset[x])
        data = bs.readBytes(bs.readInt()).data
        noepyLoadModel(data, mdlList)

def noepyLoadModel(bs, mdlList):
    v_offset = [(i+4) for i in findall(b'VRTB', bs)]
    i_offset = [(i+8) for i in findall(b'PIDX', bs)]
    bs.find(b'NAME')
    name = (bs.read(bs.readInt())).decode("utf-8").rstrip("\x00")
    
    bs = NoeBitStream(bs)
    ctx = rapi.rpgCreateContext()
    
    for x in range(len(v_offset)):
        rapi.rpgSetName('%s_mesh_%i' % (name, x))

        print("Reading ", '%s_mesh_%i' % (name, x))
        
        #MESH BLOCK
        bs.seek(v_offset[x])
        print(f'Read at {bs.getOffset()}')
        VBUF = bs.readBytes(bs.readInt())
        
        bs.seek(i_offset[x])
        IBUF = [bs.readUShort() for x in range (bs.readInt()//2)]
        print(len(VBUF))
        print(len(IBUF))
        stride = len(VBUF)//(max(IBUF)+1)
        print('stride:',stride)
        IBUF = struct.pack('%iH' % len(IBUF), *IBUF)
        
        rapi.rpgBindPositionBuffer(VBUF, noesis.RPGEODATA_FLOAT, stride)

        rapi.rpgBindUV1BufferOfs(VBUF, noesis.RPGEODATA_FLOAT, stride, stride-16)
            
        rapi.rpgCommitTriangles(IBUF, noesis.RPGEODATA_USHORT, len(IBUF)//2, noesis.RPGEO_TRIANGLE_STRIP)

    rapi.rpgSetOption(noesis.RPGOPT_TRIWINDBACKWARD, 1)
    mdl = rapi.rpgConstructModel()
    #mdl.setModelMaterials(NoeModelMaterials([], [material]))
    mdlList.append(mdl)

    return 1
    
def readWeight(data, stride):
    bs = NoeBitStream(data)
    
    WBUF = b''
    for x in range(len(data)//stride):
        bs.seek(stride - 8,1)
        z = [bs.readUByte() for x in range(8)] + [0]
        z[z[0]*2] = 255-sum([z[1:][x] for x in range(1,(z[0])*2,2)])
        z = [z[1:][x] for x in range(0,8,2)] + [z[1:][x] for x in range(1,8,2)]
        WBUF += struct.pack('8B', *z)
    
    return WBUF
    
def findall(p, s):
    i = s.find(p)
    while i != -1:
        yield i
        i = s.find(p, i+1)