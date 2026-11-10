"use client";
import {createContext,useContext,useMemo} from 'react';
import type {CSSProperties,ReactNode} from 'react';
import {familyIdentity,productFamilies} from '../lib/product-families';
type Row=Record<string,any>;
const Families=createContext<ReturnType<typeof productFamilies>>({});
export function ProductFamilies({inventory,children}:{inventory:Row[];children:ReactNode}){const families=useMemo(()=>productFamilies(inventory),[inventory]);return <Families.Provider value={families}>{children}</Families.Provider>}
export default function ProductName({row}:{row:Row}){
 const families=useContext(Families),family=families[familyIdentity(row)];
 const name=row.product_name??row.sellerProductName??row.product??'상품명 미확인';
 if(!family)return <strong>{name}</strong>;
 return <span className="product-family-title" data-product-family={family.key} style={{'--family-color':family.color,'--family-tint':family.tint} as CSSProperties} title="같은 상품명은 같은 색·표시를 사용합니다. 옵션과 등급은 아래에서 구분하세요."><span className="product-family-dot" aria-hidden="true"/><strong>{name}</strong><span className="product-family-tag">{family.label}</span></span>;
}
