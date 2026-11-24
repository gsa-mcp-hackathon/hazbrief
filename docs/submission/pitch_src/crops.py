from PIL import Image
U="/mnt/user-data/uploads/hazbrief-mcp/docs/"
def save(im,name,w=1500,q=84):
    im=im.convert("RGB")
    if im.width>w: im=im.resize((w,round(im.height*w/im.width)),Image.LANCZOS)
    im.save(f"img_{name}.jpg",quality=q,optimize=True); print(name,im.size)
s=Image.open(U+"evidence/hb208/live/run3_today_un1005_moved/settled.jpg")
p=Image.open(U+"evidence/hb208/live/run3_today_un1005_moved/playing.jpg")
save(s.crop((0,18,1440,795)),"hero")
box=(296,112,1076,728)
save(s.crop(box),"cloud15",900); save(p.crop(box),"cloud75",900)
f=Image.open(U+"evidence/hb208/live/run2b_today_i83_day/form.jpg")
save(f.crop((1105,150,1440,800)),"form",600)
o=Image.open(U+"evidence/hb208/live/run2b_today_i83_day/settled.jpg")
save(o.crop((0,18,1440,795)),"out",1300)
c=Image.open(U+"submission/demo/csx_night_first_view.png")
save(c.crop((1235,95,1440,930)),"check",520,90)
i=Image.open("ics201.png"); save(i.crop((0,0,2160,2560)),"ics",1300)
m=Image.open("usmap.png"); save(m.crop((0,0,1920,1400)),"map",1400)
