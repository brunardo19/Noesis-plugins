from inc_noesis import *
import binascii
import struct

# Author: Brunardo19
# Format primarily found in Dragon Ball Kai: Ultimate Butoden for Nintendo DS

# Original dse models are compressed with Nintendo DS LZ10 compression 
# and they must be decompressed before using this plugin

FIXED_POINT_SCALAR = 4096.0

GE_CMD_NOP = 0x00
GE_CMD_COLOR = 0x20
GE_CMD_TEXCOORD = 0x22
GE_CMD_VTX_16 = 0x23

def registerNoesisTypes():
    handle = noesis.register("Game Republic NDS", ".dse")
    
    noesis.setHandlerTypeCheck(handle, dseCheckType)
    
    noesis.setHandlerLoadModel(handle, dseLoadModel)
    return 1

def dseCheckType(data):
    if len(data) < 4:
        return 0
    bs = NoeBitStream(data)
    if bs.readBytes(4) != b'DSE\x00':
        return 0
    return 1

def decompress_okumura_lzss(compressed_data):
    """
    Decompresses data compressed with Okumura's LZSS algorithm (1989).
    """
    if len(compressed_data) < 4:
        raise ValueError("Data too short to contain a valid header.")

    uncompressed_size = int.from_bytes(compressed_data[0:4], byteorder='little')
    ring_buffer = bytearray(4096)
    ring_buffer_pos = 0x0FEE
    
    output = bytearray()
    src_idx = 4 
    data_length = len(compressed_data)

    while len(output) < uncompressed_size and src_idx < data_length:
        flags = compressed_data[src_idx]
        src_idx += 1
        
        for i in range(8):
            if len(output) >= uncompressed_size or src_idx >= data_length:
                break
                
            bit = (flags >> i) & 1
            
            if bit == 1:
                literal = compressed_data[src_idx]
                src_idx += 1
                
                output.append(literal)
                ring_buffer[ring_buffer_pos] = literal
                ring_buffer_pos = (ring_buffer_pos + 1) % 4096
                
            else:
                if src_idx + 1 >= data_length:
                    break
                    
                byte1 = compressed_data[src_idx]
                byte2 = compressed_data[src_idx + 1]
                src_idx += 2
                
                match_offset = byte1 | ((byte2 & 0xF0) << 4)
                match_length = (byte2 & 0x0F) + 3
                
                for _ in range(match_length):
                    if len(output) >= uncompressed_size:
                        break
                        
                    c = ring_buffer[match_offset]
                    output.append(c)
                    
                    ring_buffer[ring_buffer_pos] = c
                    match_offset = (match_offset + 1) % 4096
                    ring_buffer_pos = (ring_buffer_pos + 1) % 4096

    return bytes(output)

class DSEParser:
    def __init__(self, data):
        self.bs = NoeBitStream(data)
        self.header_end = 0x64
        self.string_data = b''
        
        self.texList = []
        self.matList = []
        self.boneList = []
        
        self.mesh_bone_map = {}
        self.mesh_definitions = []

    def _read_fixed_point_1_3_12(self, val):
        if val >= 0x8000: 
            val -= 0x10000
        return val / FIXED_POINT_SCALAR

    def _read_color_555(self, val):
        r, g, b = (val & 0x1F), (val >> 5) & 0x1F, (val >> 10) & 0x1F
        return (r / 31.0, g / 31.0, b / 31.0)

    def _read_string(self, offset):
        if offset >= len(self.string_data):
            return "out_of_bounds"
        end = self.string_data.find(b'\x00', offset)
        if end == -1: 
            return "unknown"
        return self.string_data[offset:end].decode('utf-8', errors='replace')

    def parse_header(self):
        self.bs.seek(0x22, NOESEEK_ABS)
        self.bone_count = self.bs.readUShort()
        self.mesh_count = self.bs.readUShort()
        
        self.bs.seek(0x28, NOESEEK_ABS)
        self.material_count = self.bs.readUShort()
        self.texture_count = self.bs.readUShort()

        self.bs.seek(0x34, NOESEEK_ABS)
        self.offset_mesh_table = self.bs.readUInt()
        
        self.bs.seek(0x38, NOESEEK_ABS)
        self.offset_bone_biding_table = self.bs.readUInt()
        
        self.bs.seek(0x3C, NOESEEK_ABS)
        self.offset_material_table = self.bs.readUInt()
        
        self.bs.seek(0x40, NOESEEK_ABS)
        self.offset_texture_headers = self.bs.readUInt()

        self.bs.seek(0x44, NOESEEK_ABS)
        self.geo_payload_size = self.bs.readUInt()

        self.bs.seek(0x50, NOESEEK_ABS)
        self.string_block_size = self.bs.readUInt()
        
        self.bs.seek(0x5C, NOESEEK_ABS)
        self.offset_texture_data = self.bs.readUInt()

        # Read String Block
        string_block_offset = self.header_end + self.geo_payload_size
        self.bs.seek(string_block_offset, NOESEEK_ABS)
        self.string_data = self.bs.readBytes(self.string_block_size)

    def parse_textures(self):
        for i in range(self.texture_count):
            self.bs.seek(self.header_end + self.offset_texture_headers + i * 48, NOESEEK_ABS)
            texture_name_off = self.bs.readUInt()
            texture_payload_offset = self.bs.readUInt()
            texture_uncompressed_bytes = self.bs.readUInt()
            texture_payload_length = self.bs.readUInt()
            texture_palette_offset = self.bs.readUInt()
            
            self.bs.seek(4, NOESEEK_REL) 
            texture_image_width = self.bs.readUShort()
            texture_image_height = self.bs.readUShort()
            
            self.bs.seek(8, NOESEEK_REL) 
            texture_image_mode_byte = self.bs.readByte()
            
            if texture_image_mode_byte in (0x02, 0x03):
                bpp = 4
            elif texture_image_mode_byte == 0x04:
                bpp = 8
            else:
                print("Warning: Unrecognized texture mode byte 0x{:02X} for texture index {}. Skipping.".format(texture_image_mode_byte, i))
                tex = NoeTexture("texture_{}_invalid_mode".format(i), 1, 1, b'\xFF\x00\xFF\xFF', noesis.NOESISTEX_RGBA32)
                self.texList.append(tex)
                continue
            
            # Read Palette
            self.bs.seek(self.offset_texture_data + texture_palette_offset, NOESEEK_ABS)
            palette_bytes = bytearray(self.bs.readBytes(128 if bpp == 4 else 512))
            
            
            # This is unorthodox, but it seems that the palette entries with a value of 0x03E0
            # (pure green in 5-5-5) are actually fully transparent in the game
            
            # To handle this, we set the alpha bit for all palette entries except those that are exactly 0x03E0
            # The original palette format is 5 bits for red, 5 bits for green, 5 bits for blue, and 1 bit as padding
            for p in range(0, len(palette_bytes), 2):
                if not (palette_bytes[p] == 0xE0 and palette_bytes[p+1] == 0x03):
                    palette_bytes[p+1] = palette_bytes[p+1] | 0x80
            
            # Read Payload & Name
            texture_name = self._read_string(texture_name_off)
            self.bs.seek(self.offset_texture_data + texture_payload_offset, NOESEEK_ABS)
            compressed_bytes = self.bs.readBytes(texture_payload_length)
            
            # Decompress and Decode
            raw_pixels = decompress_okumura_lzss(compressed_bytes)
            if raw_pixels and palette_bytes:
                rgba_data = rapi.imageDecodeRawPal(raw_pixels, palette_bytes, texture_image_width, texture_image_height, bpp, "r5g5b5a1")
                tex = NoeTexture(texture_name, texture_image_width, texture_image_height, rgba_data, noesis.NOESISTEX_RGBA32)
                tex.setFlags(noesis.NTEXFLAG_FILTER_NEAREST | noesis.NTEXFLAG_WRAP_MIRROR_REPEAT)
                self.texList.append(tex)

    def parse_materials(self):
        for i in range(self.material_count):
            self.bs.seek(self.header_end + self.offset_material_table + i * 36, NOESEEK_ABS)
            mat_name_off = self.bs.readUInt()
            self.bs.seek(12, NOESEEK_REL)
            mat_texture_idx = self.bs.readUByte()
            self.bs.seek(19, NOESEEK_REL)
            mat_name = self._read_string(mat_name_off)
            
            if mat_texture_idx >= len(self.texList):
                print("Warning: Material '{}' references invalid texture index {}".format(mat_name, mat_texture_idx))
                mat = NoeMaterial(mat_name, None)
            else:
                mat = NoeMaterial(mat_name, self.texList[mat_texture_idx].name)
            
            self.matList.append(mat)

    def parse_bones(self):
        for i in range(self.bone_count):
            self.bs.seek(self.header_end + i * 48, NOESEEK_ABS)
            read_matrix = [self._read_fixed_point_1_3_12(self.bs.readInt()) for _ in range(12)]
                
            read_matrix[9] = -read_matrix[9]
            read_matrix[10] = -read_matrix[10]
            read_matrix[11] = -read_matrix[11]
                
            matrix = NoeMat43((
                NoeVec3(read_matrix[0:3]),
                NoeVec3(read_matrix[3:6]),
                NoeVec3(read_matrix[6:9]),
                NoeVec3(read_matrix[9:12])
            ))
            
            bone = NoeBone(i, "bone_{:03d}".format(i), matrix, None, -1)
            self.boneList.append(bone)

    def parse_mesh_bindings(self):
        for i in range(self.mesh_count):
            self.bs.seek(self.header_end + self.offset_bone_biding_table + i * 16, NOESEEK_ABS)
            bind_name_off = self.bs.readUInt()
            bind_bone_inx = self.bs.readUInt()
            self.mesh_bone_map[i] = bind_bone_inx

    def parse_mesh_definitions(self):
        self.bs.seek(self.header_end + self.offset_mesh_table, NOESEEK_ABS)
        for i in range(self.mesh_count):
            name_off = self.bs.readUInt()
            cmd_off = self.bs.readUInt()
            unk1 = self.bs.readBytes(4)
            unk2 = self.bs.readBytes(4) 
            
            # Extract the vertex position multiplier byte (exponent)
            vert_pos_multiplier = pow(2, unk2[2]) 
            name = self._read_string(name_off)
            abs_cmd_offset = self.header_end + cmd_off
            
            self.mesh_definitions.append({
                'name': name, 
                'offset': abs_cmd_offset, 
                'vert_pos_multiplier': vert_pos_multiplier,
                'bone_index': self.mesh_bone_map.get(i, 0)
            })

    def build_geometry(self):
        for m_def in self.mesh_definitions:
            rapi.rpgSetName(m_def['name'])
            target_bone_index = m_def['bone_index']
            target_bone = self.boneList[target_bone_index]
            
            rapi.rpgSetTransform(target_bone.getMatrix())
            self.parse_mesh_commands(m_def['offset'], target_bone_index, m_def['vert_pos_multiplier'])
            rapi.rpgSetTransform(None)

    def parse_mesh_commands(self, offset, target_bone_index, vert_pos_multiplier):
        self.bs.seek(offset, NOESEEK_ABS)
        
        current_uv = (0.0, 0.0)
        current_color = (1.0, 1.0, 1.0)
        file_size = self.bs.getSize()

        while self.bs.tell() < file_size:
            opcode_val = self.bs.readUInt()
            
            # [0x01] End of Mesh Segment
            if opcode_val == 0x01:
                self.bs.readUInt() 
                break
            
            # [0x02] Mesh Start / Material Selection
            if (opcode_val & 0xFF) == 0x02:
                rapi.immBoneIndex([target_bone_index])
                rapi.immBoneWeight([1.0])
                
                tex_idx = (opcode_val >> 16) & 0xFF
                if tex_idx < len(self.matList):
                    rapi.rpgSetMaterial(self.matList[tex_idx].name)
                
                self.bs.readUInt()
                continue

            # [0x03 / 0x04] Packed Batches
            if opcode_val == 0x03 or opcode_val == 0x04:
                prim_type = noesis.RPGEO_TRIANGLE if opcode_val == 0x03 else noesis.RPGEO_QUAD_ABC_ACD
                rapi.immBegin(prim_type)

                header_data = self.bs.readBytes(28) 
                ge_cmd_count = struct.unpack('<H', header_data[4:6])[0]

                for _ in range(ge_cmd_count):
                    w = self.bs.readUInt()
                    opcodes = [w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF]
                    
                    for op in opcodes:
                        if op == GE_CMD_VTX_16:
                            w1 = self.bs.readUInt()
                            w2 = self.bs.readUInt()
                            
                            x = self._read_fixed_point_1_3_12(w1 & 0xFFFF) * vert_pos_multiplier
                            y = self._read_fixed_point_1_3_12((w1 >> 16) & 0xFFFF) * vert_pos_multiplier
                            z = self._read_fixed_point_1_3_12(w2 & 0xFFFF) * vert_pos_multiplier
                            
                            rapi.immUV2(current_uv)
                            rapi.immColor3(current_color)
                            rapi.immVertex3((x, y, z))
                            
                        elif op == GE_CMD_TEXCOORD:
                            p = self.bs.readUInt()
                            s, t = p & 0xFFFF, (p >> 16) & 0xFFFF
                            if s >= 0x8000: s -= 0x10000
                            if t >= 0x8000: t -= 0x10000
                            current_uv = (s / FIXED_POINT_SCALAR, t / FIXED_POINT_SCALAR)
                            
                        elif op == GE_CMD_COLOR:
                            p = self.bs.readUInt()
                            current_color = self._read_color_555(p & 0xFFFF)
                            
                        elif op == GE_CMD_NOP:
                            pass 

                rapi.immEnd()

            # [0x03000003 / 0x04000003] Structure Batches
            elif opcode_val == 0x03000003 or opcode_val == 0x04000003:
                prim_type = noesis.RPGEO_TRIANGLE if (opcode_val & 0xFF) == 0x03 else noesis.RPGEO_QUAD_ABC_ACD
                rapi.immBegin(prim_type)
                
                header_data = self.bs.readBytes(28)
                vertex_count = struct.unpack('<H', header_data[4:6])[0]
                
                fmt_byte = header_data[6]
                has_color = (fmt_byte & 0x0F) == 0x02
                color_at_end = (header_data[7] == 0x19)
                has_padding = (fmt_byte & 0x0F) == 0x04
                
                for _ in range(vertex_count):
                    vu = self.bs.readUShort()
                    vv = self.bs.readUShort()
                    
                    col_rgb = None
                    if has_color and not color_at_end:
                        col_rgb = self.bs.readUShort()
                    
                    vx = self.bs.readUShort()
                    vy = self.bs.readUShort()
                    vz = self.bs.readUShort()
                    
                    nx = self.bs.readUShort()
                    ny = self.bs.readUShort()
                    nz = self.bs.readUShort()
                    
                    if has_padding:
                        self.bs.readUShort()
                        self.bs.readUShort()
                        
                    if has_color and color_at_end:
                        col_rgb = self.bs.readUShort()
                    
                    if col_rgb is not None:
                        rapi.immColor3(self._read_color_555(col_rgb))
                    else:
                        rapi.immColor3(current_color) 
                    
                    x = self._read_fixed_point_1_3_12(vx) * vert_pos_multiplier
                    y = self._read_fixed_point_1_3_12(vy) * vert_pos_multiplier
                    z = self._read_fixed_point_1_3_12(vz) * vert_pos_multiplier
                    
                    u = self._read_fixed_point_1_3_12(vu)
                    v = self._read_fixed_point_1_3_12(vv)
                    
                    norm_x = self._read_fixed_point_1_3_12(nx)
                    norm_y = self._read_fixed_point_1_3_12(ny)
                    norm_z = self._read_fixed_point_1_3_12(nz)
                    
                    rapi.immNormal3((norm_x, norm_y, norm_z))
                    rapi.immUV2((u, v))
                    rapi.immVertex3((x, y, z))
                    
                rapi.immEnd()

def dseLoadModel(data, mdlList):
    ctx = rapi.rpgCreateContext()
    parser = DSEParser(data)

    # Sequence execution
    parser.parse_header()
    parser.parse_textures()
    parser.parse_materials()
    parser.parse_bones()
    parser.parse_mesh_bindings()
    parser.parse_mesh_definitions()
    parser.build_geometry()

    # Finalize Model Construction
    mdl = rapi.rpgConstructModel() 
    if mdl:
        mdl.setBones(parser.boneList)
        matData = NoeModelMaterials(parser.texList, parser.matList)
        mdl.setModelMaterials(matData)
        mdlList.append(mdl)
    

    return 1
