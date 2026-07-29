"""CornerNet-UW: rede compacta de heatmaps de cantos (estilo Deep ChArUco/DeepArUco).

Encoder-decoder leve (~1,9 M parâmetros): 4 níveis, skip connections,
saída de 4 heatmaps (um por canto do marcador). Treina em GPU de 6 GB
com folga (batch 32 @ 256x256 com AMP).
"""
import torch
import torch.nn as nn


def block(cin, cout):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1, bias=False),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1, bias=False),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
    )


class CornerNetUW(nn.Module):
    def __init__(self, ch=(24, 48, 96, 192), out=4):
        super().__init__()
        self.e1 = block(3, ch[0])
        self.e2 = block(ch[0], ch[1])
        self.e3 = block(ch[1], ch[2])
        self.e4 = block(ch[2], ch[3])
        self.pool = nn.MaxPool2d(2)
        self.u3 = nn.ConvTranspose2d(ch[3], ch[2], 2, 2)
        self.d3 = block(ch[2] * 2, ch[2])
        self.u2 = nn.ConvTranspose2d(ch[2], ch[1], 2, 2)
        self.d2 = block(ch[1] * 2, ch[1])
        self.u1 = nn.ConvTranspose2d(ch[1], ch[0], 2, 2)
        self.d1 = block(ch[0] * 2, ch[0])
        self.head = nn.Conv2d(ch[0], out, 1)

    def forward(self, x):
        s1 = self.e1(x)
        s2 = self.e2(self.pool(s1))
        s3 = self.e3(self.pool(s2))
        b = self.e4(self.pool(s3))
        x = self.d3(torch.cat([self.u3(b), s3], 1))
        x = self.d2(torch.cat([self.u2(x), s2], 1))
        x = self.d1(torch.cat([self.u1(x), s1], 1))
        return self.head(x)  # logits; usar com BCEWithLogits ou sigmoid+MSE


def corner_argmax(hm):
    """hm: (B,4,H,W) -> (B,4,2) coordenadas x,y do pico de cada canal."""
    B, C, H, W = hm.shape
    flat = hm.reshape(B, C, -1)
    idx = flat.argmax(-1)
    y = (idx // W).float()
    x = (idx % W).float()
    return torch.stack([x, y], -1), flat.max(-1).values
