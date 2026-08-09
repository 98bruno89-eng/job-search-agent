import re

t = '<div class="content-intro"><p></p> <p><strong>About Agoda</strong></p> <p>At Agoda, we bridge the world&nbsp;&nbsp;</p>'

if "<" in t and ">" in t:
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ")
    t = " ".join(t.split())

print(t)
